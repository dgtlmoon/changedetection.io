#!/usr/bin/python3

import json
import eventlet
import eventlet.wsgi

import time
import os
import getopt
import sys
import datetime
from flask import Flask, render_template, request, send_file, send_from_directory, safe_join, abort, redirect, url_for

# Local
import store

datastore = store.ChangeDetectionStore()
messages = []
app = Flask(__name__, static_url_path='/static')
app.config['STATIC_RESOURCES'] = "/app/static"

# app.config['SECRET_KEY'] = 'secret!'

# Disables caching of the templates
app.config['TEMPLATES_AUTO_RELOAD'] = True


@app.route("/", methods=['GET'])
def main_page():
    global messages

    # Show messages but once.
    output = render_template("watch-overview.html", watches=datastore.data['watching'], messages=messages)
    messages = []
    return output


@app.route("/static/<string:group>/<string:filename>", methods=['GET'])
def static_content(group, filename):
    try:
        return send_from_directory("/app/static/{}".format(group), filename=filename)
    except FileNotFoundError:
        abort(404)


@app.route("/api/add", methods=['POST'])
def api_watch_add():
    global messages

    #@todo add_watch should throw a custom Exception for validation etc
    datastore.add_watch(url=request.form.get('url'), tag=request.form.get('tag'))
    messages.append({'class':'ok', 'message': 'Saved'})

    return redirect(url_for('main_page'))
    # datastore.add_watch




def main(argv):
    ssl_mode = False
    port = 5000

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
