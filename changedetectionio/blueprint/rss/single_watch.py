

def construct_single_watch_routes(rss_blueprint, datastore):
    """
    Construct RSS feed routes for single watches.

    Args:
        rss_blueprint: The Flask blueprint to add routes to
        datastore: The ChangeDetectionStore instance
    """

    @rss_blueprint.route("/watch/<string:uuid>", methods=['GET'])
    def rss_single_watch(uuid):
        import datetime
        import time

        import pytz
        from flask import make_response, request, url_for
        from feedgen.feed import FeedGenerator
        from loguru import logger

        from build.lib.changedetectionio.blueprint.rss.blueprint import clean_entry_content
        from . import RSS_TEMPLATE_HTML_DEFAULT, RSS_TEMPLATE_PLAINTEXT_DEFAULT
        from ._util import scan_invalid_chars_in_rss
        from ...notification.handler import process_notification
        from ...notification_service import NotificationContextData, NotificationService, _check_cascading_vars


        """
        Display the most recent changes for a single watch as RSS feed.
        Returns RSS XML with multiple entries showing diffs between consecutive snapshots.
        The number of entries is controlled by the rss_diff_length setting.
        """
        # Always requires token set
        now = time.time()
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

        # Get the number of diffs to include (default: 5)
        rss_diff_length = datastore.data['settings']['application'].get('rss_diff_length', 5)

        # Calculate how many diffs we can actually show (limited by available history)
        # We need at least 2 snapshots to create 1 diff
        max_possible_diffs = len(dates) - 1
        num_diffs = min(rss_diff_length, max_possible_diffs) if rss_diff_length > 0 else max_possible_diffs

        # Create RSS feed
        fg = FeedGenerator()

        # Set title: use "label (url)" if label differs from url, otherwise just url
        watch_url = watch.get('url', '')
        # Same logic as watch-overview.html
        if datastore.data['settings']['application']['ui'].get('use_page_title_in_list') or watch.get('use_page_title_in_list'):
            watch_label = watch.label
        else:
            watch_label = watch.get('url')

        if watch_label != watch_url:
            feed_title = f'changedetection.io - {watch_label} ({watch_url})'
        else:
            feed_title = f'changedetection.io - {watch_url}'

        fg.title(feed_title)
        fg.description('Changes')
        fg.link(href='https://changedetection.io')

        # Loop through history and create RSS entries for each diff
        # Add entries in reverse order because feedgen reverses them
        # This way, the newest change appears first in the final RSS

        notification_service = NotificationService(datastore=datastore, notification_q=False)
        for i in range(num_diffs - 1, -1, -1):
            # Calculate indices for this diff (working backwards from newest)
            # i=0: compare dates[-2] to dates[-1] (most recent change)
            # i=1: compare dates[-3] to dates[-2] (previous change)
            # etc.
            date_index_to = -(i + 1)
            date_index_from = -(i + 2)
            timestamp_to = dates[date_index_to]
            timestamp_from = dates[date_index_from]


            if False:
                n_body_template = _check_cascading_vars(datastore=datastore, var_name='notification_body', watch=watch)
            else:
                if 'text' in rss_content_format:
                    n_body_template = RSS_TEMPLATE_PLAINTEXT_DEFAULT
                else:
                    n_body_template = RSS_TEMPLATE_HTML_DEFAULT

            n_object = NotificationContextData(initial_data={
                'notification_urls': ['null://just-sending-a-null-test-for-the-render-in-RSS'],
                'notification_body': n_body_template,
                'timestamp_to': timestamp_to,
                'timestamp_from': timestamp_from,
                'watch_label': watch_label,
                'notification_format': rss_content_format  # Sets the highlighting style etc
            })

            n_object = notification_service.queue_notification_for_watch(n_object=n_object,
                                                                         watch=watch,
                                                                         date_index_from=date_index_from,
                                                                         date_index_to=date_index_to)

            n_object['watch_mime_type'] = None  # Because we will always manage it as HTML more or less
            res = process_notification(n_object=n_object, datastore=datastore)
            guid = f"{watch['uuid']}/{timestamp_to}"

            fe = fg.add_entry()
            fe.link(link={'href': watch.get('url')})
            # Use formatted date in title instead of "Change 1, 2, 3"
            fe.title(title=f"{watch_label} - Change @ {res[0]['original_context']['change_datetime']}")
            # Out of range chars could also break feedgen
            content = res[0].get('body', '')
            if scan_invalid_chars_in_rss(content):
              content = clean_entry_content(content)

            fe.content(content=content, type='CDATA')
            fe.guid(guid, permalink=False)

            # Use the timestamp of the "to" snapshot for pubDate
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
        logger.debug(f"RSS Single watch built in {time.time()-now:.2f}s")

        return response
