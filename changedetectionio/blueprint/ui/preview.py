from flask import Blueprint, request, url_for, flash, render_template, redirect
import time
from loguru import logger

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.auth_decorator import login_optionally_required
from changedetectionio import html_tools

def construct_blueprint(datastore: ChangeDetectionStore):
    preview_blueprint = Blueprint('ui_preview', __name__, template_folder="../ui/templates")

    @preview_blueprint.route("/preview/<string:uuid>", methods=['GET'])
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
                content = watch.get_history_snapshot(timestamp=timestamp)

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

    return preview_blueprint
