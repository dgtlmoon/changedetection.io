#!/usr/bin/env python3
"""Everything kept under settings in changedetection.json must come back on the next startup.

_build_settings_data() writes every section under settings, but loading only restored headers / requests /
application. A field added in any other section looked saved, was dropped on the next start, and the first
commit() after that rewrote the file without it - so it "disappeared later"."""
import json
import os

from changedetectionio.store import ChangeDetectionStore


def _store(path):
    return ChangeDetectionStore(datastore_path=str(path), include_default_watches=False, version_tag='1.0.0')


def test_custom_settings_section_survives_restart_and_later_commits(tmp_path):
    ds = _store(tmp_path)
    ds.data['settings']['owner_profile'] = {'name': 'alice', 'contacts': ['a@example.com']}
    ds.commit()

    # Restart: the section is loaded back, not only present in the file
    ds = _store(tmp_path)
    assert ds.data['settings'].get('owner_profile') == {'name': 'alice', 'contacts': ['a@example.com']}

    # Any later commit (a settings save, a token being created, ...) must not erase it from disk
    ds.data['settings']['application']['pager_size'] = 25
    ds.commit()
    with open(os.path.join(tmp_path, 'changedetection.json'), encoding='utf-8') as f:
        assert json.load(f)['settings'].get('owner_profile') == {'name': 'alice', 'contacts': ['a@example.com']}

    ds = _store(tmp_path)
    assert ds.data['settings'].get('owner_profile') == {'name': 'alice', 'contacts': ['a@example.com']}


def test_known_settings_sections_still_merge_with_defaults(tmp_path):
    ds = _store(tmp_path)
    ds.data['settings']['application']['custom_field'] = 'kept'
    ds.data['settings']['requests']['custom_request_field'] = 42
    ds.commit()

    ds = _store(tmp_path)
    assert ds.data['settings']['application'].get('custom_field') == 'kept'
    assert ds.data['settings']['requests'].get('custom_request_field') == 42
    # Defaults not present in an older file are still there
    assert 'workers' in ds.data['settings']['requests']
    assert 'pager_size' in ds.data['settings']['application']
