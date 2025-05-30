
from changedetectionio.strtobool import strtobool
from flask import Blueprint, flash, redirect, url_for
from flask_login import login_required
from changedetectionio.store import ChangeDetectionStore
from changedetectionio import queuedWatchMetaData
from changedetectionio import worker_handler
from queue import PriorityQueue

PRICE_DATA_TRACK_ACCEPT = 'accepted'
PRICE_DATA_TRACK_REJECT = 'rejected'

def construct_blueprint(datastore: ChangeDetectionStore, update_q: PriorityQueue):

    price_data_follower_blueprint = Blueprint('price_data_follower', __name__)

    @login_required
    @price_data_follower_blueprint.route("/<string:uuid>/accept", methods=['GET'])
    def accept(uuid):
        datastore.data['watching'][uuid]['track_ldjson_price_data'] = PRICE_DATA_TRACK_ACCEPT
        datastore.data['watching'][uuid]['processor'] = 'restock_diff'
        datastore.data['watching'][uuid].clear_watch()
        worker_handler.queue_item_async_safe(update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))
        return redirect(url_for("watchlist.index"))

    @login_required
    @price_data_follower_blueprint.route("/<string:uuid>/reject", methods=['GET'])
    def reject(uuid):
        datastore.data['watching'][uuid]['track_ldjson_price_data'] = PRICE_DATA_TRACK_REJECT
        return redirect(url_for("watchlist.index"))


    return price_data_follower_blueprint


