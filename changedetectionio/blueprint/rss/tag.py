def construct_tag_routes(rss_blueprint, datastore):
    """
    Construct RSS feed routes for tags.

    Args:
        rss_blueprint: The Flask blueprint to add routes to
        datastore: The ChangeDetectionStore instance
    """

    @rss_blueprint.route("/tag/<string:tag_uuid>", methods=['GET'])
    def rss_tag_feed(tag_uuid):

        from flask import make_response, request, url_for
        from feedgen.feed import FeedGenerator

        from . import RSS_TEMPLATE_HTML_DEFAULT, RSS_TEMPLATE_PLAINTEXT_DEFAULT
        from ._util import (validate_rss_token, generate_watch_guid, get_rss_template,
                           get_watch_label, build_notification_context, render_notification,
                           populate_feed_entry, add_watch_categories)
        from ...notification_service import NotificationService

        """
        Display an RSS feed for all unviewed watches that belong to a specific tag.
        Returns RSS XML with entries for each unviewed watch with sufficient history.
        """
        # Validate token
        is_valid, error = validate_rss_token(datastore, request)
        if not is_valid:
            return error

        rss_content_format = datastore.data['settings']['application'].get('rss_content_format')

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
        notification_service = NotificationService(datastore=datastore, notification_q=False)
        # Find all watches with this tag
        for uuid, watch in datastore.data['watching'].items():
            #@todo  This is wrong, it needs to sort by most recently changed and then limit it  datastore.data['watching'].items().sorted(?)
            # So get all watches in this tag then sort

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

                # Include a link to the diff page
                diff_link = {'href': url_for('ui.ui_views.diff_history_page', uuid=watch['uuid'], _external=True)}

                # Get watch label
                watch_label = get_watch_label(datastore, watch)

                # Get template and build notification context
                timestamp_to = dates[-1]
                timestamp_from = dates[-2]

                # Generate GUID for this entry
                guid = generate_watch_guid(watch, timestamp_to)
                n_body_template = get_rss_template(datastore, watch, rss_content_format,
                                                   RSS_TEMPLATE_HTML_DEFAULT, RSS_TEMPLATE_PLAINTEXT_DEFAULT)

                n_object = build_notification_context(watch, timestamp_from, timestamp_to,
                                                     watch_label, n_body_template, rss_content_format)

                # Render notification
                res = render_notification(n_object, notification_service, watch, datastore)

                # Create and populate feed entry
                fe = fg.add_entry()
                title_suffix = f"Change @ {res['original_context']['change_datetime']}"
                populate_feed_entry(fe, watch, res['body'], guid, timestamp_to, link=diff_link, title_suffix=title_suffix)
                add_watch_categories(fe, watch, datastore)

        response = make_response(fg.rss_str())
        response.headers.set('Content-Type', 'application/rss+xml;charset=utf-8')
        return response
