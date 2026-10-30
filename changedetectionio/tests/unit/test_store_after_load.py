#!/usr/bin/env python3
"""Startup housekeeping runs for every datastore, not only brand-new installs: missing app_guid / RSS / API
tokens are created, removepassword.lock removes the password, version_tag is the running version.

These all used to run on every startup; the move to per-watch files put them in init_fresh_install(), where
an existing datastore never reached them."""
import json
import os

from changedetectionio.store import ChangeDetectionStore


def _store(path, version='1.0.0'):
    return ChangeDetectionStore(datastore_path=str(path), include_default_watches=False, version_tag=version)


def test_existing_datastore_gets_startup_housekeeping(tmp_path):
    # A fresh install gets everything
    ds = _store(tmp_path)
    app = ds.data['settings']['application']
    assert app.get('rss_access_token') and app.get('api_access_token') and ds.data.get('app_guid')

    # An older datastore on disk: no tokens, a password set, and the reset lockfile dropped in
    settings_file = os.path.join(tmp_path, 'changedetection.json')
    with open(settings_file) as f:
        saved = json.load(f)
    for key in ('rss_access_token', 'api_access_token'):
        saved['settings']['application'].pop(key, None)
    saved['settings']['application']['password'] = 'some-hashed-password'
    with open(settings_file, 'w') as f:
        json.dump(saved, f)
    open(os.path.join(tmp_path, 'removepassword.lock'), 'w').close()

    ds = _store(tmp_path, version='2.0.0')
    app = ds.data['settings']['application']
    assert app.get('rss_access_token'), "missing RSS token is created on load"
    assert app.get('api_access_token'), "missing API token is created on load"
    assert not app.get('password'), "removepassword.lock removes the password"
    assert not os.path.exists(os.path.join(tmp_path, 'removepassword.lock'))
    assert ds.data.get('version_tag') == '2.0.0'

    # and it sticks: the next startup keeps the same tokens
    tokens = (app['rss_access_token'], app['api_access_token'])
    ds = _store(tmp_path, version='2.0.0')
    app = ds.data['settings']['application']
    assert (app['rss_access_token'], app['api_access_token']) == tokens


def test_removepassword_lockfile_removes_password(tmp_path):
    """The documented way back in after a forgotten password: put removepassword.lock in the datastore, restart."""
    ds = _store(tmp_path)
    ds.data['settings']['application']['password'] = 'some-hashed-password'
    ds._save_settings()
    lockfile = os.path.join(tmp_path, 'removepassword.lock')
    open(lockfile, 'w').close()

    ds = _store(tmp_path)
    assert not ds.data['settings']['application'].get('password')
    assert not os.path.exists(lockfile), "used once, then removed"
