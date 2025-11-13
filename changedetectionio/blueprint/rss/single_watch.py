from flask import make_response, request, url_for
from feedgen.feed import FeedGenerator
import datetime
import pytz

from ._util import generate_watch_guid, generate_watch_diff_content


def construct_single_watch_routes(rss_blueprint, datastore):
    """
    Construct RSS feed routes for single watches.

    Args:
        rss_blueprint: The Flask blueprint to add routes to
        datastore: The ChangeDetectionStore instance
    """

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
        content, watch_label = generate_watch_diff_content(watch, dates, rss_content_format, datastore)

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
