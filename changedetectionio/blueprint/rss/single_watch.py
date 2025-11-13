from flask import make_response, request, url_for
from feedgen.feed import FeedGenerator
import datetime
import pytz
import locale

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
        Display the most recent changes for a single watch as RSS feed.
        Returns RSS XML with multiple entries showing diffs between consecutive snapshots.
        The number of entries is controlled by the rss_diff_length setting.
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
        watch_label = watch.label
        if watch_label and watch_label != watch_url:
            feed_title = f'changedetection.io - {watch_label} ({watch_url})'
        else:
            feed_title = f'changedetection.io - {watch_url}'

        fg.title(feed_title)
        fg.description('Changes')
        fg.link(href='https://changedetection.io')

        # Loop through history and create RSS entries for each diff
        # Add entries in reverse order because feedgen reverses them
        # This way, the newest change appears first in the final RSS
        for i in range(num_diffs - 1, -1, -1):
            # Calculate indices for this diff (working backwards from newest)
            # i=0: compare dates[-2] to dates[-1] (most recent change)
            # i=1: compare dates[-3] to dates[-2] (previous change)
            # etc.
            date_index_to = -(i + 1)
            date_index_from = -(i + 2)

            try:
                # Generate the diff content for this pair of snapshots
                timestamp_to = dates[date_index_to]
                timestamp_from = dates[date_index_from]

                content, watch_label = generate_watch_diff_content(
                    watch, dates, rss_content_format, datastore,
                    date_index_from=date_index_from,
                    date_index_to=date_index_to
                )

                # Generate edit watch link and add to content
                edit_watch_url = url_for('ui.ui_edit.edit_page',
                                        uuid=watch['uuid'],
                                        _external=True)

                # Add edit watch links at top and bottom of content
                if 'html' in rss_content_format:
                    edit_link_html = f'<p><a href="{edit_watch_url}">[edit watch]</a></p>'
                    # Insert after <body> and before </body>
                    content = content.replace('<body>', f'<body>\n{edit_link_html}', 1)
                    content = content.replace('</body>', f'{edit_link_html}\n</body>', 1)
                else:
                    # For plain text format, add plain text links in separate <pre> blocks
                    edit_link_top = f'<pre>[edit watch] {edit_watch_url}</pre>\n'
                    edit_link_bottom = f'\n<pre>[edit watch] {edit_watch_url}</pre>'
                    content = edit_link_top + content + edit_link_bottom

                # Create a unique GUID for this specific diff
                guid = f"{watch['uuid']}/{timestamp_to}"

                fe = fg.add_entry()

                # Include a link to the diff page with specific versions
                diff_link = {'href': url_for('ui.ui_views.diff_history_page',
                                            uuid=watch['uuid'],
                                            from_version=timestamp_from,
                                            to_version=timestamp_to,
                                            _external=True)}
                fe.link(link=diff_link)

                # Format the date using locale-aware formatting with timezone
                dt = datetime.datetime.fromtimestamp(int(timestamp_to))
                dt = dt.replace(tzinfo=pytz.UTC)

                # Get local timezone-aware datetime
                local_tz = datetime.datetime.now().astimezone().tzinfo
                local_dt = dt.astimezone(local_tz)

                # Format date with timezone - using strftime for locale awareness
                try:
                    formatted_date = local_dt.strftime('%Y-%m-%d %H:%M:%S %Z')
                except:
                    # Fallback if locale issues
                    formatted_date = local_dt.isoformat()

                # Use formatted date in title instead of "Change 1, 2, 3"
                fe.title(title=f"{watch_label} - Change @ {formatted_date}")
                fe.content(content=content, type='CDATA')
                fe.guid(guid, permalink=False)

                # Use the timestamp of the "to" snapshot for pubDate
                fe.pubDate(dt)

            except (IndexError, FileNotFoundError) as e:
                # Skip this diff if we can't generate it
                continue

        response = make_response(fg.rss_str())
        response.headers.set('Content-Type', 'application/rss+xml;charset=utf-8')
        return response
