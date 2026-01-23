import os
import time
from datetime import datetime

from flask import Blueprint, make_response, redirect, render_template, request, session, url_for
from flask_babel import gettext as _
from flask_paginate import Pagination, get_page_parameter

from changedetectionio import forms, processors
from changedetectionio.auth_decorator import login_optionally_required
from changedetectionio.store import ChangeDetectionStore


def construct_blueprint(datastore: ChangeDetectionStore, update_q, queuedWatchMetaData):
    watchlist_blueprint = Blueprint('watchlist', __name__, template_folder="templates")

    def parse_date(date_str):
        """Parse date string to timestamp. Returns None if parsing fails."""
        if not date_str:
            return None
        try:
            # Try ISO format first (YYYY-MM-DD)
            dt = datetime.strptime(date_str.strip(), '%Y-%m-%d')
            return dt.timestamp()
        except ValueError:
            return None

    def get_event_date_timestamp(watch):
        """Get event date as timestamp for comparison. Returns 0 if not available."""
        event_date = watch.get('event_date', '')
        if event_date:
            ts = parse_date(event_date)
            if ts:
                return ts
        return 0

    @watchlist_blueprint.route("/", methods=['GET'])
    @login_optionally_required
    def index():
        active_tag_req = request.args.get('tag', '').lower().strip()
        active_tag_uuid = active_tag = None

        # Be sure limit_tag is a uuid
        if active_tag_req:
            for uuid, tag in datastore.data['settings']['application'].get('tags', {}).items():
                if active_tag_req == tag.get('title', '').lower().strip() or active_tag_req == uuid:
                    active_tag = tag
                    active_tag_uuid = uuid
                    break

        # Redirect for the old rss path which used the /?rss=true
        if request.args.get('rss'):
            return redirect(url_for('rss.feed', tag=active_tag_uuid))

        op = request.args.get('op')
        if op:
            uuid = request.args.get('uuid')
            if op == 'pause':
                datastore.data['watching'][uuid].toggle_pause()
            elif op == 'mute':
                datastore.data['watching'][uuid].toggle_mute()

            datastore.needs_write = True
            return redirect(url_for('watchlist.index', tag = active_tag_uuid))

        # Sort by last_changed and add the uuid which is usually the key..
        sorted_watches = []
        with_errors = request.args.get('with_errors') == "1"
        unread_only = request.args.get('unread') == "1"
        errored_count = 0
        search_q = request.args.get('q').strip().lower() if request.args.get('q') else False

        # US-021: Advanced filtering parameters
        # Multi-tag filtering (tags[] parameter for multiselect)
        filter_tags = request.args.getlist('tags[]')
        if not filter_tags:
            filter_tags = request.args.getlist('tags')

        # Stock status filter
        stock_status = request.args.get('stock_status', 'all')

        # Date range filter (event date)
        date_from = parse_date(request.args.get('date_from', ''))
        date_to = parse_date(request.args.get('date_to', ''))
        # Make date_to inclusive (end of day)
        if date_to:
            date_to += 86400  # Add 24 hours

        for uuid, watch in datastore.data['watching'].items():
            if with_errors and not watch.get('last_error'):
                continue

            if unread_only and (watch.viewed or watch.last_changed == 0):
                continue

            # Tag filtering - supports both single tag (active_tag_uuid) and multi-tag (filter_tags)
            if active_tag_uuid and active_tag_uuid not in watch['tags']:
                continue

            # Multi-tag filtering (US-021): watch must have ALL selected tags
            if filter_tags:
                watch_tags = watch.get('tags', [])
                if not all(tag_uuid in watch_tags for tag_uuid in filter_tags):
                    continue

            if watch.get('last_error'):
                errored_count += 1

            # US-021: Stock status filtering
            if stock_status != 'all':
                # Only apply to restock_diff watches with restock info
                if watch.get('processor') == 'restock_diff' and watch.get('restock'):
                    in_stock = watch['restock'].get('in_stock')
                    if stock_status == 'available' and not in_stock:
                        continue
                    elif stock_status == 'sold_out' and in_stock:
                        continue
                elif stock_status == 'sold_out':
                    # If no restock info and filtering for sold out, skip
                    continue

            # US-021: Date range filtering (event_date field)
            if date_from or date_to:
                event_ts = get_event_date_timestamp(watch)
                if event_ts:
                    if date_from and event_ts < date_from:
                        continue
                    if date_to and event_ts > date_to:
                        continue
                elif date_from or date_to:
                    # Skip watches without event_date when filtering by date
                    continue

            # Search filtering
            if search_q:
                title = watch.get('title', '').lower()
                url = watch.get('url', '').lower()
                artist = watch.get('artist', '').lower()
                venue = watch.get('venue', '').lower()
                last_error = watch.get('last_error', '').lower() if watch.get('last_error') else ''

                if (search_q in title or search_q in url or
                    search_q in artist or search_q in venue or search_q in last_error):
                    sorted_watches.append(watch)
            else:
                sorted_watches.append(watch)

        # US-021: Get sort parameters from URL or cookies
        sort_attribute = request.args.get('sort') or request.cookies.get('sort') or 'last_changed'
        sort_order = request.args.get('order') or request.cookies.get('order') or 'desc'

        # Validate sort attribute
        valid_sort_attrs = ['date_created', 'paused', 'notification_muted', 'label',
                           'last_checked', 'last_changed', 'event_date']
        if sort_attribute not in valid_sort_attrs:
            sort_attribute = 'last_changed'

        # US-021: Pre-sort watches in Python for event_date (custom field)
        if sort_attribute == 'event_date':
            sorted_watches.sort(
                key=lambda w: get_event_date_timestamp(w),
                reverse=(sort_order == 'desc')
            )

        # Create filter form with current values
        filter_form = forms.EventFilterForm()
        filter_form.q.data = request.args.get('q', '')
        filter_form.stock_status.data = stock_status
        filter_form.date_from.data = request.args.get('date_from', '')
        filter_form.date_to.data = request.args.get('date_to', '')
        filter_form.sort.data = sort_attribute
        filter_form.order.data = sort_order

        form = forms.quickWatchForm(request.form)
        page = request.args.get(get_page_parameter(), type=int, default=1)
        total_count = len(sorted_watches)

        pagination = Pagination(page=page,
                                total=total_count,
                                per_page=datastore.data['settings']['application'].get('pager_size', 50),
                                css_framework="semantic",
                                display_msg=_('displaying <b>{start} - {end}</b> {record_name} in total <b>{total}</b>'),
                                record_name=_('records'))

        sorted_tags = sorted(datastore.data['settings']['application'].get('tags').items(), key=lambda x: x[1]['title'])

        output = render_template(
            "watch-overview.html",
            active_tag=active_tag,
            active_tag_uuid=active_tag_uuid,
            app_rss_token=datastore.data['settings']['application'].get('rss_access_token'),
            datastore=datastore,
            errored_count=errored_count,
            extra_classes='has-queue' if not update_q.empty() else '',
            filter_form=filter_form,
            filter_tags=filter_tags,
            form=form,
            generate_tag_colors=processors.generate_processor_badge_colors,
            guid=datastore.data['app_guid'],
            has_proxies=datastore.proxy_list,
            hosted_sticky=not os.getenv("SALTED_PASS", False),
            now_time_server=round(time.time()),
            pagination=pagination,
            processor_badge_css=processors.get_processor_badge_css(),
            processor_badge_texts=processors.get_processor_badge_texts(),
            processor_descriptions=processors.get_processor_descriptions(),
            queue_size=update_q.qsize(),
            queued_uuids=update_q.get_queued_uuids(),
            search_q=request.args.get('q', '').strip(),
            sort_attribute=sort_attribute,
            sort_order=sort_order,
            stock_status=stock_status,
            system_default_fetcher=datastore.data['settings']['application'].get('fetch_backend'),
            tags=sorted_tags,
            unread_changes_count=datastore.unread_changes_count,
            watches=sorted_watches
        )

        if session.get('share-link'):
            del (session['share-link'])

        resp = make_response(output)

        # The template can run on cookie or url query info
        if request.args.get('sort'):
            resp.set_cookie('sort', request.args.get('sort'))
        if request.args.get('order'):
            resp.set_cookie('order', request.args.get('order'))

        return resp

    return watchlist_blueprint
