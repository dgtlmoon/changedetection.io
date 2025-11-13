
from changedetectionio.store import ChangeDetectionStore
from flask import Blueprint

from . import tag as tag_routes
from . import main_feed
from . import single_watch

def construct_blueprint(datastore: ChangeDetectionStore):
    """
    Construct and configure the RSS blueprint with all routes.

    Args:
        datastore: The ChangeDetectionStore instance

    Returns:
        The configured Flask blueprint
    """
    rss_blueprint = Blueprint('rss', __name__)

    # Register all route modules
    main_feed.construct_main_feed_routes(rss_blueprint, datastore)
    single_watch.construct_single_watch_routes(rss_blueprint, datastore)
    tag_routes.construct_tag_routes(rss_blueprint, datastore)

    return rss_blueprint