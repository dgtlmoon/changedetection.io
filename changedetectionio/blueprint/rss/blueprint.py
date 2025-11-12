
from changedetectionio.jinja2_custom import render as jinja_render
from changedetectionio.notification.handler import apply_service_tweaks
from changedetectionio.store import ChangeDetectionStore
from feedgen.feed import FeedGenerator
from flask import Blueprint, make_response, request, url_for, redirect
from loguru import logger
import datetime
import pytz
import re
import time


BAD_CHARS_REGEX=r'[\x00-\x08\x0B\x0C\x0E-\x1F]'

# Anything that is not text/UTF-8 should be stripped before it breaks feedgen (such as binary data etc)
def scan_invalid_chars_in_rss(content):
    for match in re.finditer(BAD_CHARS_REGEX, content):
        i = match.start()
        bad_char = content[i]
        hex_value = f"0x{ord(bad_char):02x}"
        # Grab context
        start = max(0, i - 20)
        end = min(len(content), i + 21)
        context = content[start:end].replace('\n', '\\n').replace('\r', '\\r')
        logger.warning(f"Invalid char {hex_value} at pos {i}: ...{context}...")
        # First match is enough
        return True

    return False


def clean_entry_content(content):
    cleaned = re.sub(BAD_CHARS_REGEX, '', content)
    return cleaned

def construct_blueprint(datastore: ChangeDetectionStore):
    rss_blueprint = Blueprint('rss', __name__)

    # Helper function to generate GUID for RSS entries
    def generate_watch_guid(watch):
        """Generate a unique GUID for a watch RSS entry."""
        return f"{watch['uuid']}/{watch.last_changed}"

    # Helper function to generate diff content for a watch
    def generate_watch_diff_content(watch, dates, rss_content_format):
        """
        Generate HTML diff content for a watch given its history dates.
        Returns the rendered HTML content ready for RSS/display.
        """
        from changedetectionio import diff

        # Same logic as watch-overview.html
        if datastore.data['settings']['application']['ui'].get('use_page_title_in_list') or watch.get('use_page_title_in_list'):
            watch_label = watch.label
        else:
            watch_label = watch.get('url')

        try:
            html_diff = diff.render_diff(
                previous_version_file_contents=watch.get_history_snapshot(timestamp=dates[-2]),
                newest_version_file_contents=watch.get_history_snapshot(timestamp=dates[-1]),
                include_equal=False
            )

            requested_output_format = datastore.data['settings']['application'].get('rss_content_format')
            url, html_diff, n_title = apply_service_tweaks(url='', n_body=html_diff, n_title=None, requested_output_format=requested_output_format)

        except FileNotFoundError as e:
            html_diff = f"History snapshot file for watch {watch.get('uuid')}@{watch.last_changed} - '{watch.get('title')} not found."

        rss_template = "{{watch_title}} had a change.\n\n{{html_diff}}\n"
        if 'html' in rss_content_format:
            rss_template = "<html><body>\n<h4><a href=\"{{watch_url}}\">{{watch_title}}</a></h4>\n<p>{{html_diff}}</p>\n</body></html>\n"

        content = jinja_render(template_str=rss_template, watch_title=watch_label, html_diff=html_diff, watch_url=watch.link)

        # Out of range chars could also break feedgen
        if scan_invalid_chars_in_rss(content):
            content = clean_entry_content(content)

        return content, watch_label

    # Some RSS reader situations ended up with rss/ (forward slash after RSS) due
    # to some earlier blueprint rerouting work, it should goto feed.
    @rss_blueprint.route("/", methods=['GET'])
    def extraslash():
        return redirect(url_for('rss.feed'))

    # Import the login decorator if needed
    # from changedetectionio.auth_decorator import login_optionally_required
    @rss_blueprint.route("", methods=['GET'])
    def feed():
        now = time.time()
        # Always requires token set
        app_rss_token = datastore.data['settings']['application'].get('rss_access_token')
        rss_url_token = request.args.get('token')
        rss_content_format = datastore.data['settings']['application'].get('rss_content_format')

        if rss_url_token != app_rss_token:
            return "Access denied, bad token", 403

        from changedetectionio import diff
        limit_tag = request.args.get('tag', '').lower().strip()
        # Be sure limit_tag is a uuid
        for uuid, tag in datastore.data['settings']['application'].get('tags', {}).items():
            if limit_tag == tag.get('title', '').lower().strip():
                limit_tag = uuid

        # Sort by last_changed and add the uuid which is usually the key..
        sorted_watches = []

        # @todo needs a .itemsWithTag() or something - then we can use that in Jinaj2 and throw this away
        for uuid, watch in datastore.data['watching'].items():
            # @todo tag notification_muted skip also (improve Watch model)
            if datastore.data['settings']['application'].get('rss_hide_muted_watches') and watch.get('notification_muted'):
                continue
            if limit_tag and not limit_tag in watch['tags']:
                continue
            watch['uuid'] = uuid
            sorted_watches.append(watch)

        sorted_watches.sort(key=lambda x: x.last_changed, reverse=False)

        fg = FeedGenerator()
        fg.title('changedetection.io')
        fg.description('Feed description')
        fg.link(href='https://changedetection.io')

        for watch in sorted_watches:

            dates = list(watch.history.keys())
            # Re #521 - Don't bother processing this one if theres less than 2 snapshots, means we never had a change detected.
            if len(dates) < 2:
                continue

            if not watch.viewed:
                # Re #239 - GUID needs to be individual for each event
                # @todo In the future make this a configurable link back (see work on BASE_URL https://github.com/dgtlmoon/changedetection.io/pull/228)
                guid = generate_watch_guid(watch)
                fe = fg.add_entry()

                # Include a link to the diff page, they will have to login here to see if password protection is enabled.
                # Description is the page you watch, link takes you to the diff JS UI page
                # Dict val base_url will get overriden with the env var if it is set.
                ext_base_url = datastore.data['settings']['application'].get('active_base_url')
                # @todo fix

                # Because we are called via whatever web server, flask should figure out the right path (
                diff_link = {'href': url_for('ui.ui_views.diff_history_page', uuid=watch['uuid'], _external=True)}

                fe.link(link=diff_link)

                content, watch_label = generate_watch_diff_content(watch, dates, rss_content_format)

                fe.title(title=watch_label)
                fe.content(content=content, type='CDATA')
                fe.guid(guid, permalink=False)
                dt = datetime.datetime.fromtimestamp(int(watch.newest_history_key))
                dt = dt.replace(tzinfo=pytz.UTC)
                fe.pubDate(dt)

        response = make_response(fg.rss_str())
        response.headers.set('Content-Type', 'application/rss+xml;charset=utf-8')
        logger.trace(f"RSS generated in {time.time() - now:.3f}s")
        return response

    @rss_blueprint.route("/watch/<string:uuid>", methods=['GET'])
    def rss_single_watch(uuid):
        """
        Display the most recent change for a single watch as RSS feed.
        Returns RSS XML with a single entry showing the diff between the last two snapshots.
        """
        # Always requires token set
        app_rss_token = datastore.data['settings']['application'].get('rss_access_token')
        rss_url_token = request.args.get('token')
        rss_content_format = datastore.data['settings']['application'].get('rss_content_format')

        if rss_url_token != app_rss_token:
            return "Access denied, bad token", 403

        # Get the watch by UUID
        watch = datastore.data['watching'].get(uuid)
        if not watch:
            return f"Watch with UUID {uuid} not found", 404

        # Check if watch has at least 2 history snapshots
        dates = list(watch.history.keys())
        if len(dates) < 2:
            return f"Watch {uuid} does not have enough history snapshots to show changes (need at least 2)", 400

        # Add uuid to watch for proper functioning
        watch['uuid'] = uuid

        # Generate the diff content using the shared helper function
        content, watch_label = generate_watch_diff_content(watch, dates, rss_content_format)

        # Create RSS feed with single entry
        fg = FeedGenerator()
        fg.title(f'changedetection.io - {watch.label}')
        fg.description('Changes')
        fg.link(href='https://changedetection.io')

        # Add single entry for this watch
        guid = generate_watch_guid(watch)
        fe = fg.add_entry()

        # Include a link to the diff page
        diff_link = {'href': url_for('ui.ui_views.diff_history_page', uuid=watch['uuid'], _external=True)}
        fe.link(link=diff_link)

        fe.title(title=watch_label)
        fe.content(content=content, type='CDATA')
        fe.guid(guid, permalink=False)
        dt = datetime.datetime.fromtimestamp(int(watch.newest_history_key))
        dt = dt.replace(tzinfo=pytz.UTC)
        fe.pubDate(dt)

        response = make_response(fg.rss_str())
        response.headers.set('Content-Type', 'application/rss+xml;charset=utf-8')
        return response

    return rss_blueprint