from flask import make_response, request, url_for, redirect



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
        from feedgen.feed import FeedGenerator
        from loguru import logger
        import datetime
        import pytz
        import time

        from . import RSS_TEMPLATE_HTML_DEFAULT, RSS_TEMPLATE_PLAINTEXT_DEFAULT
        from ._util import generate_watch_guid, scan_invalid_chars_in_rss, clean_entry_content
        from ...notification.handler import process_notification
        from ...notification_service import NotificationContextData, NotificationService

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

        # @todo doesnt actually sort anything
        # @todo needs a .itemsWithTag() or something - then we can use that in Jinaj2 and throw this away
        for uuid, watch in datastore.data['watching'].items():
            # @todo tag notification_muted skip also (improve Watch model)
            if datastore.data['settings']['application'].get('rss_hide_muted_watches') and watch.get('notification_muted'):
                continue
            if limit_tag and not limit_tag in watch['tags']:
                continue
            sorted_watches.append(watch)

        sorted_watches.sort(key=lambda x: x.last_changed, reverse=False)

        fg = FeedGenerator()
        fg.title('changedetection.io')
        fg.description('Feed description')
        fg.link(href='https://changedetection.io')
        notification_service = NotificationService(datastore=datastore, notification_q=False)

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
                if datastore.data['settings']['application']['ui'].get('use_page_title_in_list') or watch.get('use_page_title_in_list'):
                    watch_label = watch.label
                else:
                    watch_label = watch.get('url')
                timestamp_to = dates[-1]
                timestamp_from = dates[-2]
                # Because we are called via whatever web server, flask should figure out the right path (
                diff_link = {'href': url_for('ui.ui_views.diff_history_page', uuid=watch['uuid'], _external=True)}

                fe.link(link=diff_link)
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
                                                                             watch=watch)

                n_object['watch_mime_type'] = None  # Because we will always manage it as HTML more or less
                res = process_notification(n_object=n_object, datastore=datastore)


                fe.title(title=watch_label)
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
        logger.trace(f"RSS generated in {time.time() - now:.3f}s")
        return response
