import time
import datetime
import pytz
from flask import Blueprint, make_response, request, url_for
from loguru import logger
from feedgen.feed import FeedGenerator

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.safe_jinja import render as jinja_render

def construct_blueprint(datastore: ChangeDetectionStore):
    rss_blueprint = Blueprint('rss', __name__)

    @rss_blueprint.route("/", methods=['GET'])
    def feed():
        now = time.time()
        # Always requires token set
        app_rss_token = datastore.data['settings']['application'].get('rss_access_token')
        rss_url_token = request.args.get('token')
        if rss_url_token != app_rss_token:
            return "Access denied, bad token", 403

        from changedetectionio import diff
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
                guid = "{}/{}".format(watch['uuid'], watch.last_changed)
                fe = fg.add_entry()

                # Include a link to the diff page, they will have to login here to see if password protection is enabled.
                # Description is the page you watch, link takes you to the diff JS UI page
                # Dict val base_url will get overriden with the env var if it is set.
                ext_base_url = datastore.data['settings']['application'].get('active_base_url')

                # Because we are called via whatever web server, flask should figure out the right path (
                diff_link = {'href': url_for('diff_history_page', uuid=watch['uuid'], _external=True)}

                fe.link(link=diff_link)

                # @todo watch should be a getter - watch.get('title') (internally if URL else..)

                watch_title = watch.get('title') if watch.get('title') else watch.get('url')
                fe.title(title=watch_title)

                html_diff = diff.render_diff(previous_version_file_contents=watch.get_history_snapshot(dates[-2]),
                                             newest_version_file_contents=watch.get_history_snapshot(dates[-1]),
                                             include_equal=False,
                                             line_feed_sep="<br>")

                # @todo Make this configurable and also consider html-colored markup
                # @todo User could decide if <link> goes to the diff page, or to the watch link
                rss_template = "<html><body>\n<h4><a href=\"{{watch_url}}\">{{watch_title}}</a></h4>\n<p>{{html_diff}}</p>\n</body></html>\n"
                content = jinja_render(template_str=rss_template, watch_title=watch_title, html_diff=html_diff, watch_url=watch.link)

                fe.content(content=content, type='CDATA')

                fe.guid(guid, permalink=False)
                dt = datetime.datetime.fromtimestamp(int(watch.newest_history_key))
                dt = dt.replace(tzinfo=pytz.UTC)
                fe.pubDate(dt)

        response = make_response(fg.rss_str())
        response.headers.set('Content-Type', 'application/rss+xml;charset=utf-8')
        logger.trace(f"RSS generated in {time.time() - now:.3f}s")
        return response

    return rss_blueprint