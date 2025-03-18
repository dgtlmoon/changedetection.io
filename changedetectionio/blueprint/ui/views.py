from flask import Blueprint, request, redirect, url_for, flash, render_template, make_response, send_from_directory, abort
from flask_login import current_user
import os
import time
from copy import deepcopy

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.auth_decorator import login_optionally_required
from changedetectionio import html_tools

def construct_blueprint(datastore: ChangeDetectionStore, update_q, queuedWatchMetaData):
    views_blueprint = Blueprint('ui_views', __name__, template_folder="../ui/templates")
    
    @views_blueprint.route("/preview/<string:uuid>", methods=['GET'])
    @login_optionally_required
    def preview_page(uuid):
        content = []
        versions = []
        timestamp = None

        # More for testing, possible to return the first/only
        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()

        try:
            watch = datastore.data['watching'][uuid]
        except KeyError:
            flash("No history found for the specified link, bad link?", "error")
            return redirect(url_for('index'))

        system_uses_webdriver = datastore.data['settings']['application']['fetch_backend'] == 'html_webdriver'
        extra_stylesheets = [url_for('static_content', group='styles', filename='diff.css')]

        is_html_webdriver = False
        if (watch.get('fetch_backend') == 'system' and system_uses_webdriver) or watch.get('fetch_backend') == 'html_webdriver' or watch.get('fetch_backend', '').startswith('extra_browser_'):
            is_html_webdriver = True
        triggered_line_numbers = []
        if datastore.data['watching'][uuid].history_n == 0 and (watch.get_error_text() or watch.get_error_snapshot()):
            flash("Preview unavailable - No fetch/check completed or triggers not reached", "error")
        else:
            # So prepare the latest preview or not
            preferred_version = request.args.get('version')
            versions = list(watch.history.keys())
            timestamp = versions[-1]
            if preferred_version and preferred_version in versions:
                timestamp = preferred_version

            try:
                versions = list(watch.history.keys())
                content = watch.get_history_snapshot(timestamp)

                triggered_line_numbers = html_tools.strip_ignore_text(content=content,
                                                                      wordlist=watch['trigger_text'],
                                                                      mode='line numbers'
                                                                      )

            except Exception as e:
                content.append({'line': f"File doesnt exist or unable to read timestamp {timestamp}", 'classes': ''})

        output = render_template("preview.html",
                                 content=content,
                                 current_version=timestamp,
                                 history_n=watch.history_n,
                                 extra_stylesheets=extra_stylesheets,
                                 extra_title=f" - Diff - {watch.label} @ {timestamp}",
                                 triggered_line_numbers=triggered_line_numbers,
                                 current_diff_url=watch['url'],
                                 screenshot=watch.get_screenshot(),
                                 watch=watch,
                                 uuid=uuid,
                                 is_html_webdriver=is_html_webdriver,
                                 last_error=watch['last_error'],
                                 last_error_text=watch.get_error_text(),
                                 last_error_screenshot=watch.get_error_snapshot(),
                                 versions=versions
                                )

        return output

    @views_blueprint.route("/diff/<string:uuid>", methods=['GET', 'POST'])
    @login_optionally_required
    def diff_history_page(uuid):
        from changedetectionio import forms

        # More for testing, possible to return the first/only
        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()

        extra_stylesheets = [url_for('static_content', group='styles', filename='diff.css')]
        try:
            watch = datastore.data['watching'][uuid]
        except KeyError:
            flash("No history found for the specified link, bad link?", "error")
            return redirect(url_for('index'))

        # For submission of requesting an extract
        extract_form = forms.extractDataForm(request.form)
        if request.method == 'POST':
            if not extract_form.validate():
                flash("An error occurred, please see below.", "error")

            else:
                extract_regex = request.form.get('extract_regex').strip()
                output = watch.extract_regex_from_all_history(extract_regex)
                if output:
                    watch_dir = os.path.join(datastore.datastore_path, uuid)
                    response = make_response(send_from_directory(directory=watch_dir, path=output, as_attachment=True))
                    response.headers['Content-type'] = 'text/csv'
                    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                    response.headers['Pragma'] = 'no-cache'
                    response.headers['Expires'] = 0
                    return response

                flash('Nothing matches that RegEx', 'error')
                redirect(url_for('ui_views.diff_history_page', uuid=uuid)+'#extract')

        history = watch.history
        dates = list(history.keys())

        if len(dates) < 2:
            flash("Not enough saved change detection snapshots to produce a report.", "error")
            return redirect(url_for('index'))

        # Save the current newest history as the most recently viewed
        datastore.set_last_viewed(uuid, time.time())

        # Read as binary and force decode as UTF-8
        # Windows may fail decode in python if we just use 'r' mode (chardet decode exception)
        from_version = request.args.get('from_version')
        from_version_index = -2  # second newest
        if from_version and from_version in dates:
            from_version_index = dates.index(from_version)
        else:
            from_version = dates[from_version_index]

        try:
            from_version_file_contents = watch.get_history_snapshot(dates[from_version_index])
        except Exception as e:
            from_version_file_contents = f"Unable to read to-version at index {dates[from_version_index]}.\n"

        to_version = request.args.get('to_version')
        to_version_index = -1
        if to_version and to_version in dates:
            to_version_index = dates.index(to_version)
        else:
            to_version = dates[to_version_index]

        try:
            to_version_file_contents = watch.get_history_snapshot(dates[to_version_index])
        except Exception as e:
            to_version_file_contents = "Unable to read to-version at index{}.\n".format(dates[to_version_index])

        screenshot_url = watch.get_screenshot()

        system_uses_webdriver = datastore.data['settings']['application']['fetch_backend'] == 'html_webdriver'

        is_html_webdriver = False
        if (watch.get('fetch_backend') == 'system' and system_uses_webdriver) or watch.get('fetch_backend') == 'html_webdriver' or watch.get('fetch_backend', '').startswith('extra_browser_'):
            is_html_webdriver = True

        password_enabled_and_share_is_off = False
        if datastore.data['settings']['application'].get('password') or os.getenv("SALTED_PASS", False):
            password_enabled_and_share_is_off = not datastore.data['settings']['application'].get('shared_diff_access')

        output = render_template("diff.html",
                                 current_diff_url=watch['url'],
                                 from_version=str(from_version),
                                 to_version=str(to_version),
                                 extra_stylesheets=extra_stylesheets,
                                 extra_title=f" - Diff - {watch.label}",
                                 extract_form=extract_form,
                                 is_html_webdriver=is_html_webdriver,
                                 last_error=watch['last_error'],
                                 last_error_screenshot=watch.get_error_snapshot(),
                                 last_error_text=watch.get_error_text(),
                                 left_sticky=True,
                                 newest=to_version_file_contents,
                                 newest_version_timestamp=dates[-1],
                                 password_enabled_and_share_is_off=password_enabled_and_share_is_off,
                                 from_version_file_contents=from_version_file_contents,
                                 to_version_file_contents=to_version_file_contents,
                                 screenshot=screenshot_url,
                                 uuid=uuid,
                                 versions=dates, # All except current/last
                                 watch_a=watch
                                 )

        return output

    @views_blueprint.route("/form/add/quickwatch", methods=['POST'])
    @login_optionally_required
    def form_quick_watch_add():
        from changedetectionio import forms
        form = forms.quickWatchForm(request.form)

        if not form.validate():
            for widget, l in form.errors.items():
                flash(','.join(l), 'error')
            return redirect(url_for('index'))

        url = request.form.get('url').strip()
        if datastore.url_exists(url):
            flash(f'Warning, URL {url} already exists', "notice")

        add_paused = request.form.get('edit_and_watch_submit_button') != None
        processor = request.form.get('processor', 'text_json_diff')
        new_uuid = datastore.add_watch(url=url, tag=request.form.get('tags').strip(), extras={'paused': add_paused, 'processor': processor})

        if new_uuid:
            if add_paused:
                flash('Watch added in Paused state, saving will unpause.')
                return redirect(url_for('ui.ui_edit.edit_page', uuid=new_uuid, unpause_on_save=1, tag=request.args.get('tag')))
            else:
                # Straight into the queue.
                update_q.put(queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': new_uuid}))
                flash("Watch added.")

        return redirect(url_for('index', tag=request.args.get('tag','')))

    return views_blueprint