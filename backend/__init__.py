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
# https://distill.io/features
# proxy per check
#  - flask_cors, itsdangerous,MarkupSafe

import time
import os
import timeago

import threading
import queue

from flask import Flask, render_template, request, send_file, send_from_directory,  abort, redirect, url_for

datastore = None

# Local
running_update_threads = []
ticker_thread = None

messages = []
extra_stylesheets = []

update_q = queue.Queue()

app = Flask(__name__, static_url_path="/var/www/change-detection/backen/static")

# Stop browser caching of assets
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

app.config['STOP_THREADS'] = False

# Disables caching of the templates
app.config['TEMPLATES_AUTO_RELOAD'] = True


# We use the whole watch object from the store/JSON so we can see if there's some related status in terms of a thread
# running or something similar.
@app.template_filter('format_last_checked_time')
def _jinja2_filter_datetime(watch_obj, format="%Y-%m-%d %H:%M:%S"):
    # Worker thread tells us which UUID it is currently processing.
    for t in running_update_threads:
        if t.current_uuid == watch_obj['uuid']:
            return "Checking now.."

    if watch_obj['last_checked'] == 0:
        return 'Not yet'

    return timeago.format(int(watch_obj['last_checked']), time.time())


# @app.context_processor
# def timeago():
#    def _timeago(lower_time, now):
#        return timeago.format(lower_time, now)
#    return dict(timeago=_timeago)

@app.template_filter('format_timestamp_timeago')
def _jinja2_filter_datetimestamp(timestamp, format="%Y-%m-%d %H:%M:%S"):
    return timeago.format(timestamp, time.time())
    # return timeago.format(timestamp, time.time())
    # return datetime.datetime.utcfromtimestamp(timestamp).strftime(format)


def changedetection_app(config=None, datastore_o=None):
    global datastore
    datastore = datastore_o
    # Hmm
    app.config.update(dict(DEBUG=True))
    app.config.update(config or {})

    # Setup cors headers to allow all domains
    # https://flask-cors.readthedocs.io/en/latest/
    #    CORS(app)

    # https://github.com/pallets/flask/blob/93dd1709d05a1cf0e886df6223377bdab3b077fb/examples/tutorial/flaskr/__init__.py#L39
    # You can divide up the stuff like this

    @app.route("/", methods=['GET'])
    def index():
        global messages

        limit_tag = request.args.get('tag')

        # Sort by last_changed and add the uuid which is usually the key..
        sorted_watches = []
        for uuid, watch in datastore.data['watching'].items():

            if limit_tag != None:
                # Support for comma separated list of tags.
                for tag_in_watch in watch['tag'].split(','):
                    tag_in_watch = tag_in_watch.strip()
                    if tag_in_watch == limit_tag:
                        watch['uuid'] = uuid
                        sorted_watches.append(watch)

            else:
                watch['uuid'] = uuid
                sorted_watches.append(watch)

        sorted_watches.sort(key=lambda x: x['last_changed'], reverse=True)

        existing_tags = datastore.get_all_tags()
        output = render_template("watch-overview.html",
                                 watches=sorted_watches,
                                 messages=messages,
                                 tags=existing_tags,
                                 active_tag=limit_tag)

        # Show messages but once.
        messages = []
        return output

    @app.route("/scrub", methods=['GET', 'POST'])
    def scrub_page():
        from pathlib import Path

        global messages

        if request.method == 'POST':
            confirmtext = request.form.get('confirmtext')

            if confirmtext == 'scrub':

                for txt_file_path in Path(app.config['datastore_path']).rglob('*.txt'):
                    os.unlink(txt_file_path)

                for uuid, watch in datastore.data['watching'].items():
                    watch['last_checked'] = 0
                    watch['last_changed'] = 0
                    watch['previous_md5'] = None
                    watch['history'] = {}

                datastore.needs_write = True
                messages.append({'class': 'ok', 'message': 'Cleaned all version history.'})
            else:
                messages.append({'class': 'error', 'message': 'Wrong confirm text.'})

            return redirect(url_for('index'))

        return render_template("scrub.html")

    @app.route("/edit", methods=['GET', 'POST'])
    def edit_page():
        global messages
        import validators

        if request.method == 'POST':
            uuid = request.args.get('uuid')

            url = request.form.get('url').strip()
            tag = request.form.get('tag').strip()

            # Extra headers
            form_headers = request.form.get('headers').strip().split("\n")
            extra_headers = {}
            if form_headers:
                for header in form_headers:
                    if len(header):
                        parts = header.split(':', 1)
                        if len(parts) == 2:
                            extra_headers.update({parts[0].strip(): parts[1].strip()})

            validators.url(url)  # @todo switch to prop/attr/observer
            datastore.data['watching'][uuid].update({'url': url,
                                                     'tag': tag,
                                                     'headers': extra_headers})
            datastore.needs_write = True

            messages.append({'class': 'ok', 'message': 'Updated watch.'})

            return redirect(url_for('index'))

        else:

            uuid = request.args.get('uuid')
            output = render_template("edit.html", uuid=uuid, watch=datastore.data['watching'][uuid], messages=messages)

        return output

    @app.route("/settings", methods=['GET', "POST"])
    def settings_page():
        global messages
        if request.method == 'POST':
            try:
                minutes = int(request.values.get('minutes').strip())
            except ValueError:
                messages.append({'class': 'error', 'message': "Invalid value given, use an integer."})

            else:
                if minutes >= 5:
                    datastore.data['settings']['requests']['minutes_between_check'] = minutes
                    datastore.needs_write = True

                    messages.append({'class': 'ok', 'message': "Updated"})
                else:
                    messages.append(
                        {'class': 'error', 'message': "Must be atleast 5 minutes."})

        output = render_template("settings.html", messages=messages,
                                 minutes=datastore.data['settings']['requests']['minutes_between_check'])
        messages = []

        return output

    @app.route("/import", methods=['GET', "POST"])
    def import_page():
        import validators
        global messages
        remaining_urls = []

        good = 0

        if request.method == 'POST':
            urls = request.values.get('urls').split("\n")
            for url in urls:
                url = url.strip()
                if len(url) and validators.url(url):
                    new_uuid = datastore.add_watch(url=url.strip(), tag="")
                    # Straight into the queue.
                    update_q.put(new_uuid)
                    good += 1
                else:
                    if len(url):
                        remaining_urls.append(url)

            messages.append({'class': 'ok', 'message': "{} Imported, {} Skipped.".format(good, len(remaining_urls))})

        if len(remaining_urls) == 0:
            return redirect(url_for('index'))
        else:
            output = render_template("import.html",
                                     messages=messages,
                                     remaining="\n".join(remaining_urls)
                                     )
            messages = []
        return output

    @app.route("/diff/<string:uuid>", methods=['GET'])
    def diff_history_page(uuid):
        global messages

        # More for testing, possible to return the first/only
        if uuid == 'first':
            uuid= list(datastore.data['watching'].keys()).pop()

        extra_stylesheets = ['/static/css/diff.css']
        try:
            watch = datastore.data['watching'][uuid]
        except KeyError:
            messages.append({'class': 'error', 'message': "No history found for the specified link, bad link?"})
            return redirect(url_for('index'))

        dates = list(watch['history'].keys())
        # Convert to int, sort and back to str again
        dates = [int(i) for i in dates]
        dates.sort(reverse=True)
        dates = [str(i) for i in dates]


        if len(dates) < 2:
            messages.append({'class': 'error', 'message': "Not enough saved change detection snapshots to produce a report."})
            return redirect(url_for('index'))

        # Save the current newest history as the most recently viewed
        datastore.set_last_viewed(uuid, dates[0])

        newest_file = watch['history'][dates[0]]
        with open(newest_file, 'r') as f:
            newest_version_file_contents = f.read()

        previous_version = request.args.get('previous_version')

        try:
            previous_file = watch['history'][previous_version]
        except KeyError:
            # Not present, use a default value, the second one in the sorted list.
            previous_file = watch['history'][dates[1]]

        with open(previous_file, 'r') as f:
            previous_version_file_contents = f.read()

        output = render_template("diff.html", watch_a=watch,
                                 messages=messages,
                                 newest=newest_version_file_contents,
                                 previous=previous_version_file_contents,
                                 extra_stylesheets=extra_stylesheets,
                                 versions=dates[1:],
                                 newest_version_timestamp=dates[0],
                                 current_previous_version=str(previous_version),
                                 current_diff_url=watch['url'])

        return output

    @app.route("/favicon.ico", methods=['GET'])
    def favicon():
        return send_from_directory("/app/static/images", filename="favicon.ico")

    # We're good but backups are even better!
    @app.route("/backup", methods=['GET'])
    def get_backup():
        import zipfile
        from pathlib import Path

        # create a ZipFile object
        backupname = "changedetection-backup-{}.zip".format(int(time.time()))

        # We only care about UUIDS from the current index file
        uuids = list(datastore.data['watching'].keys())

        with zipfile.ZipFile(os.path.join(app.config['datastore_path'], backupname), 'w',
                             compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as zipObj:

            # Be sure we're written fresh
            datastore.sync_to_json()

            # Add the index
            zipObj.write(os.path.join(app.config['datastore_path'], "url-watches.json"))
            # Add any snapshot data we find
            for txt_file_path in Path(app.config['datastore_path']).rglob('*.txt'):
                parent_p = txt_file_path.parent
                if parent_p.name in uuids:
                    zipObj.write(txt_file_path)

        return send_file(os.path.join(app.config['datastore_path'], backupname),
                         as_attachment=True,
                         mimetype="application/zip",
                         attachment_filename=backupname)

    @app.route("/static/<string:group>/<string:filename>", methods=['GET'])
    def static_content(group, filename):
        # These files should be in our subdirectory
        full_path = os.path.realpath(__file__)
        p = os.path.dirname(full_path)

        try:
            return send_from_directory("{}/static/{}".format(p, group), filename=filename)
        except FileNotFoundError:
            abort(404)

    @app.route("/api/add", methods=['POST'])
    def api_watch_add():
        global messages

        # @todo add_watch should throw a custom Exception for validation etc
        new_uuid = datastore.add_watch(url=request.form.get('url').strip(), tag=request.form.get('tag').strip())
        # Straight into the queue.
        update_q.put(new_uuid)

        messages.append({'class': 'ok', 'message': 'Watch added.'})
        return redirect(url_for('index'))

    @app.route("/api/delete", methods=['GET'])
    def api_delete():
        global messages
        uuid = request.args.get('uuid')
        datastore.delete(uuid)
        messages.append({'class': 'ok', 'message': 'Deleted.'})

        return redirect(url_for('index'))

    @app.route("/api/checknow", methods=['GET'])
    def api_watch_checknow():

        global messages

        tag = request.args.get('tag')
        uuid = request.args.get('uuid')
        i = 0

        running_uuids = []
        for t in running_update_threads:
            running_uuids.append(t.current_uuid)

        # @todo check thread is running and skip

        if uuid:
            if uuid not in running_uuids:
                update_q.put(uuid)
            i = 1

        elif tag != None:
            # Items that have this current tag
            for watch_uuid, watch in datastore.data['watching'].items():
                if (tag != None and tag in watch['tag']):
                    i += 1
                    if watch_uuid not in running_uuids:
                        update_q.put(watch_uuid)
        else:
            # No tag, no uuid, add everything.
            for watch_uuid, watch in datastore.data['watching'].items():
                i += 1
                if watch_uuid not in running_uuids:
                    update_q.put(watch_uuid)

        messages.append({'class': 'ok', 'message': "{} watches are rechecking.".format(i)})
        return redirect(url_for('index', tag=tag))

    # @todo handle ctrl break
    ticker_thread = threading.Thread(target=ticker_thread_check_time_launch_checks).start()

    return app


# Requests for checking on the site use a pool of thread Workers managed by a Queue.
class Worker(threading.Thread):
    current_uuid = None

    def __init__(self, q, *args, **kwargs):
        self.q = q
        super().__init__(*args, **kwargs)

    def run(self):
        from backend import fetch_site_status

        update_handler = fetch_site_status.perform_site_check(datastore=datastore)

        while True:

            try:
                uuid = self.q.get(block=True, timeout=1)
            except queue.Empty:
                # We have a chance to kill this thread that needs to monitor for new jobs..
                # Delays here would be caused by a current response object pending
                # @todo switch to threaded response handler
                if app.config['STOP_THREADS']:
                    return
            else:
                self.current_uuid = uuid

                if uuid in list(datastore.data['watching'].keys()):

                    try:
                        changed_detected, result, contents = update_handler.run(uuid)

                    except PermissionError as s:
                        app.logger.error("File permission error updating", uuid, str(s))
                    else:
                        if result:

                            datastore.update_watch(uuid=uuid, update_obj=result)
                            if changed_detected:
                                # A change was detected
                                datastore.save_history_text(uuid=uuid, contents=contents, result_obj=result)


                self.current_uuid = None  # Done
                self.q.task_done()


# Thread runner to check every minute, look for new watches to feed into the Queue.
def ticker_thread_check_time_launch_checks():
    # Spin up Workers.
    for _ in range(datastore.data['settings']['requests']['workers']):
        new_worker = Worker(update_q)
        running_update_threads.append(new_worker)
        new_worker.start()

    # Every minute check for new UUIDs to follow up on
    while True:

        if app.config['STOP_THREADS']:
            return

        running_uuids = []
        for t in running_update_threads:
            running_uuids.append(t.current_uuid)

        # Look at the dataset, find a stale watch to process
        minutes = datastore.data['settings']['requests']['minutes_between_check']
        for uuid, watch in datastore.data['watching'].items():
            if watch['last_checked'] <= time.time() - (minutes * 60):

                # @todo maybe update_q.queue is enough?
                if not uuid in running_uuids and uuid not in update_q.queue:
                    update_q.put(uuid)

        # Should be low so we can break this out in testing
        time.sleep(1)
