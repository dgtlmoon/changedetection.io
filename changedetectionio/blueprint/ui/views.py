from flask import Blueprint, request, redirect, url_for, flash, render_template, make_response, send_from_directory, abort
import os
import time
import re
from loguru import logger
from markupsafe import Markup

from changedetectionio.diff import REMOVED_STYLE, ADDED_STYLE, DIFF_HTML_LABEL_REMOVED, DIFF_HTML_LABEL_ADDED
from changedetectionio.store import ChangeDetectionStore
from changedetectionio.auth_decorator import login_optionally_required
from changedetectionio import html_tools, diff
from changedetectionio import worker_handler

def construct_blueprint(datastore: ChangeDetectionStore, update_q, queuedWatchMetaData, watch_check_update):
    views_blueprint = Blueprint('ui_views', __name__, template_folder="../ui/templates")

    @views_blueprint.app_template_filter('diff_unescape_difference_spans')
    def diff_unescape_difference_spans(content):
        """Emulate Jinja2's auto-escape, then selectively unescape our diff spans."""
        from markupsafe import escape

        if not content:
            return Markup('')

        # Step 1: Escape everything like Jinja2 would (this makes it XSS-safe)
        escaped_content = escape(str(content))

        # Step 2: Simple regex to unescape only our exact diff spans
        # Unescape opening tags with exact styles
        # This matches the styles used in DIFF_HTML_LABEL_REMOVED, DIFF_HTML_LABEL_ADDED, etc.
        result = re.sub(
            rf'&lt;span style=&#34;({REMOVED_STYLE}|{ADDED_STYLE})&#34; title=&#34;([A-Za-z0-9]+)&#34;&gt;',
            r'<span style="\1" title="\2">',
            str(escaped_content),
            flags=re.IGNORECASE
        )

        # Unescape closing tags (but only as many as we opened)
        open_count = result.count('<span style=')
        close_count = str(escaped_content).count('&lt;/span&gt;')

        # Replace up to the number of spans we opened
        for _ in range(min(open_count, close_count)):
            result = result.replace('&lt;/span&gt;', '</span>', 1)

        return Markup(result)

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
            return redirect(url_for('watchlist.index'))

        system_uses_webdriver = datastore.data['settings']['application']['fetch_backend'] == 'html_webdriver'
        extra_stylesheets = [url_for('static_content', group='styles', filename='diff.css')]

        is_html_webdriver = False
        if (watch.get('fetch_backend') == 'system' and system_uses_webdriver) or watch.get('fetch_backend') == 'html_webdriver' or watch.get('fetch_backend', '').startswith('extra_browser_'):
            is_html_webdriver = True

        triggered_line_numbers = []
        ignored_line_numbers = []
        blocked_line_numbers = []

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
                                                                      wordlist=watch.get('trigger_text'),
                                                                      mode='line numbers'
                                                                      )
                ignored_line_numbers = html_tools.strip_ignore_text(content=content,
                                                                      wordlist=watch.get('ignore_text'),
                                                                      mode='line numbers'
                                                                      )
                blocked_line_numbers = html_tools.strip_ignore_text(content=content,
                                                                      wordlist=watch.get("text_should_not_be_present"),
                                                                      mode='line numbers'
                                                                      )
            except Exception as e:
                content.append({'line': f"File doesnt exist or unable to read timestamp {timestamp}", 'classes': ''})

        output = render_template("preview.html",
                                 content=content,
                                 current_diff_url=watch['url'],
                                 current_version=timestamp,
                                 extra_stylesheets=extra_stylesheets,
                                 extra_title=f" - Diff - {watch.label} @ {timestamp}",
                                 highlight_ignored_line_numbers=ignored_line_numbers,
                                 highlight_triggered_line_numbers=triggered_line_numbers,
                                 highlight_blocked_line_numbers=blocked_line_numbers,
                                 history_n=watch.history_n,
                                 is_html_webdriver=is_html_webdriver,
                                 last_error=watch['last_error'],
                                 last_error_screenshot=watch.get_error_snapshot(),
                                 last_error_text=watch.get_error_text(),
                                 screenshot=watch.get_screenshot(),
                                 uuid=uuid,
                                 versions=versions,
                                 watch=watch,
                                 )

        return output

    @views_blueprint.route("/diff/<string:uuid>", methods=['POST'])
    @login_optionally_required
    def diff_history_page_build_report(uuid):
        from changedetectionio import forms

        # More for testing, possible to return the first/only
        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()

        try:
            watch = datastore.data['watching'][uuid]
        except KeyError:
            flash("No history found for the specified link, bad link?", "error")
            return redirect(url_for('watchlist.index'))

        # For submission of requesting an extract
        extract_form = forms.extractDataForm(formdata=request.form,
                                             data={'extract_regex': request.form.get('extract_regex', '')}
                                             )
        if not extract_form.validate():
            flash("An error occurred, please see below.", "error")
            return _render_diff_template(uuid, extract_form)

        else:
            extract_regex = request.form.get('extract_regex', '').strip()
            output = watch.extract_regex_from_all_history(extract_regex)
            if output:
                watch_dir = os.path.join(datastore.datastore_path, uuid)
                response = make_response(send_from_directory(directory=watch_dir, path=output, as_attachment=True))
                response.headers['Content-type'] = 'text/csv'
                response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                response.headers['Pragma'] = 'no-cache'
                response.headers['Expires'] = "0"
                return response

            flash('No matches found while scanning all of the watch history for that RegEx.', 'error')
        return redirect(url_for('ui.ui_views.diff_history_page', uuid=uuid) + '#extract')

    def _render_diff_template(uuid, extract_form=None):
        """Helper function to render the diff template with all required data"""
        from changedetectionio import forms

        # More for testing, possible to return the first/only
        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()

        extra_stylesheets = [url_for('static_content', group='styles', filename='diff.css')]
        try:
            watch = datastore.data['watching'][uuid]
        except KeyError:
            flash("No history found for the specified link, bad link?", "error")
            return redirect(url_for('watchlist.index'))

        # Use provided form or create a new one
        if extract_form is None:
            extract_form = forms.extractDataForm(formdata=request.form,
                                                 data={'extract_regex': request.form.get('extract_regex', '')}
                                                 )

        history = watch.history
        dates = list(history.keys())

        # If a "from_version" was requested, then find it (or the closest one)
        # Also set "from version" to be the closest version to the one that was last viewed.

        best_last_viewed_timestamp = watch.get_from_version_based_on_last_viewed
        from_version_timestamp = best_last_viewed_timestamp if best_last_viewed_timestamp else dates[-2]
        from_version = request.args.get('from_version', from_version_timestamp )

        # Use the current one if nothing was specified
        to_version = request.args.get('to_version', str(dates[-1]))

        try:
            to_version_file_contents = watch.get_history_snapshot(timestamp=to_version)
        except Exception as e:
            logger.error(f"Unable to read watch history to-version for version {to_version}: {str(e)}")
            to_version_file_contents = f"Unable to read to-version at {to_version}.\n"

        try:
            from_version_file_contents = watch.get_history_snapshot(timestamp=from_version)
        except Exception as e:
            logger.error(f"Unable to read watch history from-version for version {from_version}: {str(e)}")
            from_version_file_contents = f"Unable to read to-version {from_version}.\n"

        screenshot_url = watch.get_screenshot()

        system_uses_webdriver = datastore.data['settings']['application']['fetch_backend'] == 'html_webdriver'

        is_html_webdriver = False
        if (watch.get('fetch_backend') == 'system' and system_uses_webdriver) or watch.get('fetch_backend') == 'html_webdriver' or watch.get('fetch_backend', '').startswith('extra_browser_'):
            is_html_webdriver = True

        password_enabled_and_share_is_off = False
        if datastore.data['settings']['application'].get('password') or os.getenv("SALTED_PASS", False):
            password_enabled_and_share_is_off = not datastore.data['settings']['application'].get('shared_diff_access')

        datastore.set_last_viewed(uuid, time.time())
        content = diff.render_diff(from_version_file_contents,
                                   to_version_file_contents,
                                   include_equal=True,
                                   html_colour=False,
                                   ignore_junk=datastore.data['settings']['application'].get('ignore_whitespace', False),
                                   )

        return render_template("diff.html",
                                 content=content,
                                 current_diff_url=watch['url'],
                                 extra_stylesheets=extra_stylesheets,
                                 extra_title=f" - Diff - {watch.label}",
                                 extract_form=extract_form,
                                 from_version=str(from_version),
                                 is_html_webdriver=is_html_webdriver,
                                 last_error=watch['last_error'],
                                 last_error_screenshot=watch.get_error_snapshot(),
                                 last_error_text=watch.get_error_text(),
                                 left_sticky=True,
                                 newest=to_version_file_contents,
                                 newest_version_timestamp=dates[-1],
                                 password_enabled_and_share_is_off=password_enabled_and_share_is_off,
                                 screenshot=screenshot_url,
                                 to_version=str(to_version),
                                 uuid=uuid,
                                 versions=dates, # All except current/last
                                 watch_a=watch
                                 )

    @views_blueprint.route("/diff/<string:uuid>", methods=['GET'])
    @login_optionally_required
    def diff_history_page(uuid):
        return _render_diff_template(uuid)

    @views_blueprint.route("/form/add/quickwatch", methods=['POST'])
    @login_optionally_required
    def form_quick_watch_add():
        from changedetectionio import forms
        form = forms.quickWatchForm(request.form)

        if not form.validate():
            for widget, l in form.errors.items():
                flash(','.join(l), 'error')
            return redirect(url_for('watchlist.index'))

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
                worker_handler.queue_item_async_safe(update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': new_uuid}))
                flash("Watch added.")

        return redirect(url_for('watchlist.index', tag=request.args.get('tag','')))

    return views_blueprint