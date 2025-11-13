from flask import make_response, request, url_for
from feedgen.feed import FeedGenerator
import datetime
import pytz


from ._util import generate_watch_guid, generate_watch_diff_content


def construct_tag_routes(rss_blueprint, datastore):
    """
    Construct RSS feed routes for tags.

    Args:
        rss_blueprint: The Flask blueprint to add routes to
        datastore: The ChangeDetectionStore instance
    """

    @rss_blueprint.route("/tag/<string:tag_uuid>", methods=['GET'])
    def rss_tag_feed(tag_uuid):
        """
        Display an RSS feed for all unviewed watches that belong to a specific tag.
        Returns RSS XML with entries for each unviewed watch with sufficient history.
        """
        # Always requires token set
        app_rss_token = datastore.data['settings']['application'].get('rss_access_token')
        rss_url_token = request.args.get('token')
        rss_content_format = datastore.data['settings']['application'].get('rss_content_format')

        if rss_url_token != app_rss_token:
            return "Access denied, bad token", 403

        # Verify tag exists
        tag = datastore.data['settings']['application'].get('tags', {}).get(tag_uuid)
        if not tag:
            return f"Tag with UUID {tag_uuid} not found", 404

        tag_title = tag.get('title', 'Unknown Tag')

        # Create RSS feed
        fg = FeedGenerator()
        fg.title(f'changedetection.io - {tag_title}')
        fg.description(f'Changes for watches tagged with {tag_title}')
        fg.link(href='https://changedetection.io')

        # Find all watches with this tag
        for uuid, watch in datastore.data['watching'].items():
            # Skip if watch doesn't have this tag
            if tag_uuid not in watch.get('tags', []):
                continue

            # Skip muted watches if configured
            if datastore.data['settings']['application'].get('rss_hide_muted_watches') and watch.get('notification_muted'):
                continue

            # Check if watch has at least 2 history snapshots
            dates = list(watch.history.keys())
            if len(dates) < 2:
                continue

            # Only include unviewed watches
            if not watch.viewed:
                # Add uuid to watch for proper functioning
                watch['uuid'] = uuid

                # Generate GUID for this entry
                guid = generate_watch_guid(watch)
                fe = fg.add_entry()

                # Include a link to the diff page
                diff_link = {'href': url_for('ui.ui_views.diff_history_page', uuid=watch['uuid'], _external=True)}
                fe.link(link=diff_link)

                # Generate diff content
                content, watch_label = generate_watch_diff_content(watch, dates, rss_content_format, datastore)

                fe.title(title=watch_label)
                fe.content(content=content, type='CDATA')
                fe.guid(guid, permalink=False)
                dt = datetime.datetime.fromtimestamp(int(watch.newest_history_key))
                dt = dt.replace(tzinfo=pytz.UTC)
                fe.pubDate(dt)

        response = make_response(fg.rss_str())
        response.headers.set('Content-Type', 'application/rss+xml;charset=utf-8')
        return response
