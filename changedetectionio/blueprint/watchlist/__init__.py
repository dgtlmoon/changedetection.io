import os
import time

from flask import Blueprint, request, make_response, render_template, redirect, url_for, flash, session
from flask_login import current_user
from flask_paginate import Pagination, get_page_parameter

from changedetectionio import forms
from changedetectionio.store import ChangeDetectionStore
from changedetectionio.auth_decorator import login_optionally_required

def construct_blueprint(datastore: ChangeDetectionStore, update_q, queuedWatchMetaData):
    watchlist_blueprint = Blueprint('watchlist', __name__, template_folder="templates")
    
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
        errored_count = 0
        search_q = request.args.get('q').strip().lower() if request.args.get('q') else False
        for uuid, watch in datastore.data['watching'].items():
            if with_errors and not watch.get('last_error'):
                continue

            if active_tag_uuid and not active_tag_uuid in watch['tags']:
                    continue
            if watch.get('last_error'):
                errored_count += 1

            if search_q:
                if (watch.get('title') and search_q in watch.get('title').lower()) or search_q in watch.get('url', '').lower():
                    sorted_watches.append(watch)
                elif watch.get('last_error') and search_q in watch.get('last_error').lower():
                    sorted_watches.append(watch)
            else:
                sorted_watches.append(watch)

        form = forms.quickWatchForm(request.form)
        page = request.args.get(get_page_parameter(), type=int, default=1)
        total_count = len(sorted_watches)

        pagination = Pagination(page=page,
                                total=total_count,
                                per_page=datastore.data['settings']['application'].get('pager_size', 50), css_framework="semantic")

        sorted_tags = sorted(datastore.data['settings']['application'].get('tags').items(), key=lambda x: x[1]['title'])

        output = render_template(
            "watch-overview.html",
            active_tag=active_tag,
            active_tag_uuid=active_tag_uuid,
            app_rss_token=datastore.data['settings']['application'].get('rss_access_token'),
            datastore=datastore,
            errored_count=errored_count,
            form=form,
            guid=datastore.data['app_guid'],
            has_proxies=datastore.proxy_list,
            has_unviewed=datastore.has_unviewed,
            hosted_sticky=os.getenv("SALTED_PASS", False) == False,
            now_time_server=round(time.time()),
            pagination=pagination,
            queued_uuids=[q_uuid.item['uuid'] for q_uuid in update_q.queue],
            search_q=request.args.get('q', '').strip(),
            sort_attribute=request.args.get('sort') if request.args.get('sort') else request.cookies.get('sort'),
            sort_order=request.args.get('order') if request.args.get('order') else request.cookies.get('order'),
            system_default_fetcher=datastore.data['settings']['application'].get('fetch_backend'),
            tags=sorted_tags,
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