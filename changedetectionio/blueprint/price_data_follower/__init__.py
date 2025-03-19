
from flask import Blueprint, flash, redirect, url_for
from flask_login import login_required
from queue import PriorityQueue
from changedetectionio import queuedWatchMetaData
from changedetectionio.processors.constants import PRICE_DATA_TRACK_ACCEPT, PRICE_DATA_TRACK_REJECT


def construct_blueprint(datastore, update_q: PriorityQueue):

    price_data_follower_blueprint = Blueprint('price_data_follower', __name__)
    @login_required
    @price_data_follower_blueprint.route("/<string:uuid>/accept", methods=['GET'])
    def accept(uuid):
        datastore.data['watching'][uuid]['track_ldjson_price_data'] = PRICE_DATA_TRACK_ACCEPT
        datastore.data['watching'][uuid]['processor'] = 'restock_diff'
        datastore.data['watching'][uuid].clear_watch()
        update_q.put(queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))
        return redirect(url_for("index"))

    @login_required
    @price_data_follower_blueprint.route("/<string:uuid>/reject", methods=['GET'])
    def reject(uuid):
        datastore.data['watching'][uuid]['track_ldjson_price_data'] = PRICE_DATA_TRACK_REJECT
        return redirect(url_for("index"))


    return price_data_follower_blueprint


