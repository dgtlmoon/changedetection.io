"""
Example plugin - adds its own page at /hello-world, shown inside the normal app layout, with a link to it in
the left sidebar.

Install it with `pip install .` from the directory above this one, see example_plugins/README.md.
It is not active until installed (or registered), nothing scans example_plugins/ for plugins.
"""
from flask import Blueprint, render_template

from changedetectionio.plugin_api import hookimpl

# Name the blueprint after the plugin, a name that's already taken is skipped at startup.
# The template lives in templates/cdio_example_hello_world/ so its path can't clash with a core
# template or another plugin's.
blueprint = Blueprint('cdio_example_hello_world', __name__, template_folder='templates')

# Set by register_blueprints() below
_datastore = None


@blueprint.route('/')
def hello():
    # The template extends base.html, so it gets the header, menu and styles of every other page
    return render_template('cdio_example_hello_world/hello.html',
                           watch_count=len(_datastore.data['watching']))


@hookimpl
def register_blueprints(datastore):
    """Called once at startup. The page needs the same login as the rest of the UI, return
    'login_required': False as well only if you secure the routes some other way."""
    global _datastore
    _datastore = datastore
    return {'blueprint': blueprint, 'url_prefix': '/hello-world'}


@hookimpl
def register_sidebar_items(datastore):
    """A link to the page in the left sidebar, after the built-in ones. Called on every page render, so
    stay in memory. 'endpoint' rather than a hard-coded URL keeps sub-path deployments working."""
    return {
        'label': 'Hello world',
        'title': 'Hello world (example plugin)',
        'endpoint': 'cdio_example_hello_world.hello',
        'icon': 'smile',  # a Feather icon name, or give 'svg' with your own <svg class="action-icon" ...>
        'active_prefix': 'cdio_example_hello_world.',  # highlighted while on any of this plugin's pages
    }
