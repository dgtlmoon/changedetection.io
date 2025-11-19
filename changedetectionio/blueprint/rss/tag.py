def construct_tag_routes(rss_blueprint, datastore):
    """
    Construct RSS feed routes for tags.

    Args:
        rss_blueprint: The Flask blueprint to add routes to
        datastore: The ChangeDetectionStore instance
    """

    @rss_blueprint.route("/tag/<string:tag_uuid>", methods=['GET'])
    def rss_tag_feed(tag_uuid):

        import datetime

        import pytz
        from flask import make_response, request, url_for
        from feedgen.feed import FeedGenerator

        from . import RSS_TEMPLATE_HTML_DEFAULT, RSS_TEMPLATE_PLAINTEXT_DEFAULT
        from ._util import scan_invalid_chars_in_rss,generate_watch_guid,clean_entry_content
        from ...notification.handler import process_notification
        from ...notification_service import NotificationContextData, NotificationService, _check_cascading_vars

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

                # Generate GUID for this entry
                guid = generate_watch_guid(watch)
                fe = fg.add_entry()

                # Include a link to the diff page
                diff_link = {'href': url_for('ui.ui_views.diff_history_page', uuid=watch['uuid'], _external=True)}
                fe.link(link=diff_link)

                # Same logic as watch-overview.html
                if datastore.data['settings']['application']['ui'].get('use_page_title_in_list') or watch.get('use_page_title_in_list'):
                    watch_label = watch.label
                else:
                    watch_label = watch.get('url')


                if False:
                    n_body_template = _check_cascading_vars(datastore=datastore, var_name='notification_body', watch=watch)
                else:
                    if 'text' in rss_content_format:
                        n_body_template = RSS_TEMPLATE_PLAINTEXT_DEFAULT
                    else:
                        n_body_template = RSS_TEMPLATE_HTML_DEFAULT

                timestamp_to = dates[-1]
                timestamp_from = dates[-2]
                n_object = NotificationContextData(initial_data={
                    'notification_urls': ['null://just-sending-a-null-test-for-the-render-in-RSS'],
                    'notification_body': n_body_template,
                    'timestamp_to': timestamp_to,
                    'timestamp_from': timestamp_from,
                    'watch_label': watch_label,
                    'notification_format': rss_content_format  # Sets the highlighting style etc
                })

                n_object = notification_service.queue_notification_for_watch(n_object=n_object,
                                                                             watch=watch)

                n_object['watch_mime_type'] = None  # Because we will always manage it as HTML more or less
                res = process_notification(n_object=n_object, datastore=datastore)


                fe.title(title=f"{watch_label} - Change @ {res[0]['original_context']['change_datetime']}")
                content = res[0]['body']
                if scan_invalid_chars_in_rss(content):
                    content = clean_entry_content(content)

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
        return response
