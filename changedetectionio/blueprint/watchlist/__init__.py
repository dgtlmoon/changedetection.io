import os
import time

from flask import Blueprint, request, make_response, render_template, redirect, url_for, flash, session
from flask_paginate import Pagination, get_page_parameter
from flask_babel import gettext as _

from changedetectionio import forms
from changedetectionio import processors
from changedetectionio import worker_pool
from changedetectionio.store import ChangeDetectionStore
from changedetectionio.auth_decorator import login_optionally_required

def construct_blueprint(datastore: ChangeDetectionStore, update_q, queuedWatchMetaData):
    watchlist_blueprint = Blueprint('watchlist', __name__, template_folder="templates")

    # --- Watchlist filtering, shared by the rendered list (index) and the
    # "/uuids" endpoint (used by the client "select all matching" feature) so the
    # two can never drift out of sync. ---
    def _resolve_active_tag_uuid(active_tag_req):
        if not active_tag_req:
            return None
        for uuid, tag in datastore.data['settings']['application'].get('tags', {}).items():
            if active_tag_req == tag.get('title', '').lower().strip() or active_tag_req == uuid:
                return uuid
        return None

    def _list_filters_from_args(args, active_tag_uuid):
        return {
            'with_errors': args.get('with_errors') == "1",
            'unread_only': args.get('unread') == "1",
            'processor': args.get('processor', '').strip(),
            'tag_uuid': active_tag_uuid,
            'search_q': args.get('q').strip().lower() if args.get('q') else False,
        }

    # Status/tag/processor filters (everything except the text search).
    def _watch_passes_prefilter(watch, f):
        if f['with_errors'] and not watch.get('last_error'):
            return False
        if f['unread_only'] and (watch.viewed or watch.last_changed == 0):
            return False
        if f['tag_uuid'] and f['tag_uuid'] not in watch['tags']:
            return False
        if f['processor'] and watch.get('processor') != f['processor']:
            return False
        return True

    def _watch_passes_search(watch, f):
        search_q = f['search_q']
        if not search_q:
            return True
        if (watch.get('title') and search_q in watch.get('title').lower()) or search_q in watch.get('url', '').lower():
            return True
        if watch.get('last_error') and search_q in watch.get('last_error').lower():
            return True
        return False


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

            datastore.data['watching'][uuid].commit()
            return redirect(url_for('watchlist.index', tag = active_tag_uuid))

        # Sort by last_changed and add the uuid which is usually the key..
        sorted_watches = []
        active_processor = request.args.get('processor', '').strip()
        errored_count = 0
        list_filters = _list_filters_from_args(request.args, active_tag_uuid)
        for uuid, watch in datastore.data['watching'].items():
            if not _watch_passes_prefilter(watch, list_filters):
                continue
            # errored_count reflects the tag/processor/status-filtered set (pre-search)
            if watch.get('last_error'):
                errored_count += 1
            if _watch_passes_search(watch, list_filters):
                sorted_watches.append(watch)

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

        proxy_list = datastore.proxy_list

        from changedetectionio.llm.evaluator import get_llm_config as _get_llm_config
        from changedetectionio.llm.ui_strings import LLM_INTENT_WATCH_PLACEHOLDER
        llm_configured = bool(_get_llm_config(datastore))

        output = render_template(
            "watch-overview.html",
            active_tag=active_tag,
            active_tag_uuid=active_tag_uuid,
            active_processor=active_processor,
            checking_now_size=len(worker_pool.get_running_uuids()),
            app_rss_token=datastore.data['settings']['application'].get('rss_access_token'),
            datastore=datastore,
            errored_count=errored_count,
            extra_classes=' '.join(filter(None, ['has-queue' if not update_q.empty() else '', 'llm-configured' if llm_configured else ''])),
            form=form,
            generate_tag_colors=processors.generate_processor_badge_colors,
            wcag_text_color=processors.wcag_text_color,
            guid=datastore.data['app_guid'],
            has_proxies=proxy_list,
            #header=_("todo - tag name etc"),
            hosted_sticky=os.getenv("SALTED_PASS", False) == False,
            now_time_server=round(time.time()),
            pagination=pagination,
            processor_badge_css=processors.get_processor_badge_css(),
            processor_badge_texts=processors.get_processor_badge_texts(),
            processor_descriptions=processors.get_processor_descriptions(),
            queue_size=update_q.qsize(),
            queued_uuids=update_q.get_queued_uuids(),
            search_q=request.args.get('q', '').strip(),
            sort_attribute=request.args.get('sort') if request.args.get('sort') else request.cookies.get('sort'),
            sort_order=request.args.get('order') if request.args.get('order') else request.cookies.get('order'),
            system_default_fetcher=datastore.data['settings']['application'].get('fetch_backend'),
            tags=sorted_tags,
            unread_changes_count=datastore.unread_changes_count,
            watches=sorted_watches,
            llm_configured=llm_configured,
            llm_intent_watch_placeholder=LLM_INTENT_WATCH_PLACEHOLDER,
        )

        # Return freed template-building memory to the OS immediately.
        # render_template allocates ~20MB of intermediate strings that are freed on return,
        # but glibc keeps those pages mapped in its arenas as RSS. malloc_trim() forces
        # glibc to release them, preventing RSS growth from concurrent Chrome connections.
        try:
            import ctypes
            ctypes.CDLL('libc.so.6').malloc_trim(0)
        except Exception:
            pass

        if session.get('share-link'):
            del (session['share-link'])

        resp = make_response(output)

        # The template can run on cookie or url query info
        if request.args.get('sort'):
            resp.set_cookie('sort', request.args.get('sort'))
        if request.args.get('order'):
            resp.set_cookie('order', request.args.get('order'))

        return resp

    @watchlist_blueprint.route("/uuids", methods=['GET'])
    @login_optionally_required
    def uuids():
        """All watch UUIDs matching the current filter (tag/search/status/processor).

        Backs the client "select all matching" feature: the watchlist page only
        renders one page of rows, so to select across pages the browser fetches the
        full matching id list from here and holds it in its selection store.
        """
        from flask import jsonify
        active_tag_uuid = _resolve_active_tag_uuid(request.args.get('tag', '').lower().strip())
        list_filters = _list_filters_from_args(request.args, active_tag_uuid)
        matching = [
            uuid for uuid, watch in datastore.data['watching'].items()
            if _watch_passes_prefilter(watch, list_filters) and _watch_passes_search(watch, list_filters)
        ]
        return jsonify({'uuids': matching})

    return watchlist_blueprint