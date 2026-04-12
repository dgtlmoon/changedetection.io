

def construct_single_watch_routes(rss_blueprint, datastore):
    """
    Construct RSS feed routes for single watches.

    Args:
        rss_blueprint: The Flask blueprint to add routes to
        datastore: The ChangeDetectionStore instance
    """

    @rss_blueprint.route("/watch/<uuid_str:uuid>", methods=['GET'])
    def rss_single_watch(uuid):
        import time

        from flask import make_response, request, Response
        from flask_babel import lazy_gettext as _l
        from feedgen.feed import FeedGenerator
        from loguru import logger

        from . import RSS_TEMPLATE_HTML_DEFAULT, RSS_TEMPLATE_PLAINTEXT_DEFAULT
        from ._util import (validate_rss_token, get_rss_template, get_watch_label,
                           build_notification_context, render_notification,
                           populate_feed_entry, add_watch_categories)
        from ...notification_service import NotificationService

        """
        Display the most recent changes for a single watch as RSS feed.
        Returns RSS XML with multiple entries showing diffs between consecutive snapshots.
        The number of entries is controlled by the rss_diff_length setting.
        """
        now = time.time()

        # Validate token
        is_valid, error = validate_rss_token(datastore, request)
        if not is_valid:
            return error

        rss_content_format = datastore.data['settings']['application'].get('rss_content_format')

        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()
        # Get the watch by UUID
        watch = datastore.data['watching'].get(uuid)
        if not watch:
            return Response(_l("Watch with UUID %(uuid)s not found", uuid=uuid), status=404, mimetype='text/plain')

        # Check if watch has at least 2 history snapshots
        dates = list(watch.history.keys())
        if len(dates) < 2:
            return Response(_l("Watch %(uuid)s does not have enough history snapshots to show changes (need at least 2)", uuid=uuid), status=400, mimetype='text/plain')

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
        watch_label = get_watch_label(datastore, watch)

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

            # Get template and build notification context
            n_body_template = get_rss_template(datastore, watch, rss_content_format,
                                               RSS_TEMPLATE_HTML_DEFAULT, RSS_TEMPLATE_PLAINTEXT_DEFAULT)

            n_object = build_notification_context(watch, timestamp_from, timestamp_to,
                                                 watch_label, n_body_template, rss_content_format)

            # Render notification with date indices
            res = render_notification(n_object, notification_service, watch, datastore,
                                     date_index_from, date_index_to)

            # Create and populate feed entry
            guid = f"{uuid}/{timestamp_to}"
            fe = fg.add_entry()
            title_suffix = f"Change @ {res['original_context']['change_datetime']}"
            populate_feed_entry(fe, watch, res.get('body', ''), guid, timestamp_to,
                              link={'href': watch.get('url')}, title_suffix=title_suffix)
            add_watch_categories(fe, watch, datastore)

        response = make_response(fg.rss_str())
        response.headers.set('Content-Type', 'application/rss+xml;charset=utf-8')
        logger.debug(f"RSS Single watch built in {time.time()-now:.2f}s")

        return response
