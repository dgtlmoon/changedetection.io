from flask import make_response, request, url_for, redirect
from feedgen.feed import FeedGenerator
from loguru import logger
import datetime
import pytz
import time

from ._util import generate_watch_guid, generate_watch_diff_content


def construct_main_feed_routes(rss_blueprint, datastore):
    """
    Construct the main RSS feed routes.

    Args:
        rss_blueprint: The Flask blueprint to add routes to
        datastore: The ChangeDetectionStore instance
    """

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

                content, watch_label = generate_watch_diff_content(watch, dates, rss_content_format, datastore)

                fe.title(title=watch_label)
                fe.content(content=content, type='CDATA')
                fe.guid(guid, permalink=False)
                dt = datetime.datetime.fromtimestamp(int(watch.newest_history_key))
                dt = dt.replace(tzinfo=pytz.UTC)
                fe.pubDate(dt)

                # Add categories based on watch tags
                for tag_uuid in watch.get('tags', []):
                    tag = datastore.data['settings']['application'].get('tags', {}).get(tag_uuid)
                    if tag:
                        tag_title = tag.get('title', '')
                        if tag_title:
                            fe.category(term=tag_title)

        response = make_response(fg.rss_str())
        response.headers.set('Content-Type', 'application/rss+xml;charset=utf-8')
        logger.trace(f"RSS generated in {time.time() - now:.3f}s")
        return response
