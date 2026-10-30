"""Plugins can mount their own Flask blueprints via the register_blueprints hookimpl.

A fresh Flask app is used per test: Flask refuses new blueprints once an app has served a
request, so the shared test app can't be reused for this.
"""
import flask_login
import pytest
from flask import Blueprint, Flask

from changedetectionio.pluggy_interface import hookimpl, plugin_manager, register_plugin_blueprints


class _FakeDatastore:
    def __init__(self, password=False):
        self.data = {'settings': {'application': {'password': password}}}


def _make_app(password=False):
    app = Flask(__name__)
    app.config['DATASTORE'] = _FakeDatastore(password=password)
    app.secret_key = 'test'
    login_manager = flask_login.LoginManager(app)
    login_manager.user_loader(lambda user_id: None)
    return app


def _blueprint(name, body):
    bp = Blueprint(name, __name__)

    @bp.route('/hello')
    def hello():
        return body

    return bp


@pytest.fixture
def register_plugin():
    names = []

    def _register(plugin, name):
        plugin_manager.register(plugin, name=name)
        names.append(name)

    yield _register
    for name in names:
        plugin_manager.unregister(name=name)


def test_blueprint_forms_are_mounted(register_plugin):
    class Plugin:
        @hookimpl
        def register_blueprints(self, datastore):
            return [
                _blueprint('test_bp_bare', 'bare'),
                {'blueprint': _blueprint('test_bp_dict', 'dict'), 'url_prefix': '/test-bp-dict'},
            ]

    class SinglePlugin:
        @hookimpl
        def register_blueprints(self, datastore):
            bp = Blueprint('test_bp_single', __name__, url_prefix='/test-bp-single')
            bp.add_url_rule('/hello', 'hello', lambda: 'single')
            return bp

    register_plugin(Plugin(), 'test_bp_plugin')
    register_plugin(SinglePlugin(), 'test_bp_single_plugin')

    app = _make_app()
    registered = register_plugin_blueprints(app, app.config['DATASTORE'])
    assert set(registered) == {'test_bp_bare', 'test_bp_dict', 'test_bp_single'}

    client = app.test_client()
    assert client.get('/hello').data == b'bare'
    assert client.get('/test-bp-dict/hello').data == b'dict'
    # url_prefix from the Blueprint itself is kept when the plugin doesn't override it
    assert client.get('/test-bp-single/hello').data == b'single'


def test_login_required_by_default(register_plugin):
    class Plugin:
        @hookimpl
        def register_blueprints(self, datastore):
            return [
                {'blueprint': _blueprint('test_bp_private', 'private'), 'url_prefix': '/private'},
                {'blueprint': _blueprint('test_bp_public', 'public'), 'url_prefix': '/public',
                 'login_required': False},
            ]

    register_plugin(Plugin(), 'test_bp_login_plugin')

    app = _make_app(password='hashed-password')
    register_plugin_blueprints(app, app.config['DATASTORE'])
    client = app.test_client()

    assert client.get('/private/hello').status_code == 401
    res = client.get('/public/hello')
    assert res.status_code == 200 and res.data == b'public'


def test_bad_entries_are_skipped(register_plugin):
    class BadPlugin:
        @hookimpl
        def register_blueprints(self, datastore):
            return [
                'not a blueprint',
                {'url_prefix': '/missing-blueprint'},
                # Name clash with a blueprint the app already has
                {'blueprint': _blueprint('core_thing', 'hijacked'), 'url_prefix': '/hijack'},
                {'blueprint': _blueprint('test_bp_good', 'good'), 'url_prefix': '/good'},
            ]

    class RaisingPlugin:
        @hookimpl
        def register_blueprints(self, datastore):
            raise RuntimeError("plugin blew up")

    register_plugin(BadPlugin(), 'test_bp_bad_plugin')
    register_plugin(RaisingPlugin(), 'test_bp_raising_plugin')

    app = _make_app()
    app.register_blueprint(_blueprint('core_thing', 'core'), url_prefix='/core')

    registered = register_plugin_blueprints(app, app.config['DATASTORE'])
    assert registered == ['test_bp_good']

    client = app.test_client()
    assert client.get('/core/hello').data == b'core'
    assert client.get('/hijack/hello').status_code == 404
    assert client.get('/good/hello').data == b'good'
