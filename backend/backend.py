#!/usr/bin/python3


# @todo logging
# @todo sort by last_changed
# @todo extra options for url like , verify=False etc.
# @todo enable https://urllib3.readthedocs.io/en/latest/user-guide.html#ssl as option?
# @todo maybe a button to reset all 'last-changed'.. so you can see it clearly when something happens since your last visit
# @todo option for interval day/6 hour/etc
# @todo on change detected, config for calling some API
# @todo make tables responsive!
# @todo fetch title into json

import json
import eventlet
import eventlet.wsgi

import time
import os
import getopt
import sys
import datetime
import timeago

import threading

from flask import Flask, render_template, request, send_file, send_from_directory, safe_join, abort, redirect, url_for

# Local
import store
import fetch_site_status

ticker_thread = None

datastore = store.ChangeDetectionStore()
messages = []
running_update_threads = {}

app = Flask(__name__, static_url_path='/static')
app.config['STATIC_RESOURCES'] = "/app/static"

# app.config['SECRET_KEY'] = 'secret!'

# Disables caching of the templates
app.config['TEMPLATES_AUTO_RELOAD'] = True


# We use the whole watch object from the store/JSON so we can see if there's some related status in terms of a thread
# running or something similar.
@app.template_filter('format_last_checked_time')
def _jinja2_filter_datetime(watch_obj, format="%Y-%m-%d %H:%M:%S"):
    global running_update_threads
    if watch_obj['uuid'] in running_update_threads:
        if running_update_threads[watch_obj['uuid']].is_alive():
            return "Checking now.."

    if watch_obj['last_checked'] == 0:
        return 'Not yet'

    return datetime.datetime.utcfromtimestamp(int(watch_obj['last_checked'])).strftime(format)

#@app.context_processor
#def timeago():
#    def _timeago(lower_time, now):
#        return timeago.format(lower_time, now)
#    return dict(timeago=_timeago)

@app.template_filter('format_timestamp_timeago')
def _jinja2_filter_datetimestamp(timestamp, format="%Y-%m-%d %H:%M:%S"):
    if timestamp == 0:
        return 'Not yet'
    return timeago.format(timestamp, time.time())
    #return timeago.format(timestamp, time.time())
    #return datetime.datetime.utcfromtimestamp(timestamp).strftime(format)


@app.route("/", methods=['GET'])
def main_page():
    global messages

    # Show messages but once.
    # maybe if the change happened more than a few days ago.. add a class

    # Sort by last_changed
    datastore.data['watching'].sort(key=lambda x: x['last_changed'], reverse=True)

    output = render_template("watch-overview.html", watches=datastore.data['watching'], messages=messages)
    messages = []
    return output


@app.route("/favicon.ico", methods=['GET'])
def favicon():
    return send_from_directory("/app/static/images", filename="favicon.ico")

@app.route("/static/<string:group>/<string:filename>", methods=['GET'])
def static_content(group, filename):
    try:
        return send_from_directory("/app/static/{}".format(group), filename=filename)
    except FileNotFoundError:
        abort(404)


@app.route("/api/add", methods=['POST'])
def api_watch_add():
    global messages

    # @todo add_watch should throw a custom Exception for validation etc
    datastore.add_watch(url=request.form.get('url').strip(), tag=request.form.get('tag').strip())
    messages.append({'class': 'ok', 'message': 'Saved'})
    launch_checks()
    return redirect(url_for('main_page'))


@app.route("/api/checknow", methods=['GET'])
def api_watch_checknow():
    global messages

    uuid = request.args.get('uuid')

    # dict would be better, this is a simple safety catch.
    for watch in datastore.data['watching']:
        if watch['uuid'] == uuid:
            # @todo cancel if already running?
            running_update_threads[uuid] = fetch_site_status.perform_site_check(uuid=uuid,
                                                                                datastore=datastore)
            running_update_threads[uuid].start()

    return redirect(url_for('main_page'))


# Can be used whenever, launch threads that need launching to update the stored information
def launch_checks():
    import fetch_site_status
    global running_update_threads

    for watch in datastore.data['watching']:
        if watch['last_checked'] <= time.time() - 3*60*60:
            running_update_threads[watch['uuid']] = fetch_site_status.perform_site_check(uuid=watch['uuid'],
                                                                                         datastore=datastore)
            running_update_threads[watch['uuid']].start()


# Thread runner to check every minute
def ticker_thread_check_time_launch_checks():
    while True:
        launch_checks()
        time.sleep(60)


def main(argv):
    ssl_mode = False
    port = 5000

    # @todo handle ctrl break
    ticker_thread = threading.Thread(target=ticker_thread_check_time_launch_checks).start()

    try:
        opts, args = getopt.getopt(argv, "sp:")
    except getopt.GetoptError:
        print('backend.py -s SSL enable -p [port]')
        sys.exit(2)

    for opt, arg in opts:
        if opt == '-s':
            ssl_mode = True

        if opt == '-p':
            port = arg

    # @todo finalise SSL config, but this should get you in the right direction if you need it.
    if ssl_mode:
        eventlet.wsgi.server(eventlet.wrap_ssl(eventlet.listen(('', port)),
                                               certfile='cert.pem',
                                               keyfile='privkey.pem',
                                               server_side=True), app)

    else:
        eventlet.wsgi.server(eventlet.listen(('', port)), app)


if __name__ == '__main__':
    main(sys.argv[1:])
