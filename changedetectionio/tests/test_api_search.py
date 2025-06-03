from copy import copy

from flask import url_for
import json
import time
from .util import live_server_setup, wait_for_all_checks


def test_api_search(client, live_server):
   #  live_server_setup(live_server) # Setup on conftest per function
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')

    watch_data = {}
    # Add some test watches
    urls = [
        'https://example.com/page1',
        'https://example.org/testing',
        'https://test-site.com/example'
    ]

    # Import the test URLs
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": "\r\n".join(urls)},
        follow_redirects=True
    )
    assert b"3 Imported" in res.data
    wait_for_all_checks(client)

    # Get a listing, it will be the first one
    watches_response = client.get(
        url_for("createwatch"),
        headers={'x-api-key': api_key}
    )


    # Add a title to one watch for title search testing
    for uuid, watch in watches_response.json.items():

        watch_data = client.get(url_for("watch", uuid=uuid),
                                follow_redirects=True,
                                headers={'x-api-key': api_key}
                                )

        if urls[0] == watch_data.json['url']:
            # HTTP PUT ( UPDATE an existing watch )
            client.put(
                url_for("watch", uuid=uuid),
                headers={'x-api-key': api_key, 'content-type': 'application/json'},
                data=json.dumps({'title': 'Example Title Test'}),
            )

    # Test search by URL
    res = client.get(url_for("search")+"?q=https://example.com/page1", headers={'x-api-key': api_key, 'content-type': 'application/json'})
    assert len(res.json) == 1
    assert list(res.json.values())[0]['url'] == urls[0]

    # Test search by URL - partial should NOT match without ?partial=true flag
    res = client.get(url_for("search")+"?q=https://example", headers={'x-api-key': api_key, 'content-type': 'application/json'})
    assert len(res.json) == 0


    # Test search by title
    res = client.get(url_for("search")+"?q=Example Title Test", headers={'x-api-key': api_key, 'content-type': 'application/json'})
    assert len(res.json) == 1
    assert list(res.json.values())[0]['url'] == urls[0]
    assert list(res.json.values())[0]['title'] == 'Example Title Test'

    # Test search that should return multiple results (partial = true)
    res = client.get(url_for("search")+"?q=https://example&partial=true", headers={'x-api-key': api_key, 'content-type': 'application/json'})
    assert len(res.json) == 2

    # Test empty search
    res = client.get(url_for("search")+"?q=", headers={'x-api-key': api_key, 'content-type': 'application/json'})
    assert res.status_code == 400

    # Add a tag to test search with tag filter
    tag_name = 'test-tag'
    res = client.post(
        url_for("tag"),
        data=json.dumps({"title": tag_name}),
        headers={'content-type': 'application/json', 'x-api-key': api_key}
    )
    assert res.status_code == 201
    tag_uuid = res.json['uuid']

    # Add the tag to one watch
    for uuid, watch in watches_response.json.items():
        if urls[2] == watch['url']:
            client.put(
                url_for("watch", uuid=uuid),
                headers={'x-api-key': api_key, 'content-type': 'application/json'},
                data=json.dumps({'tags': [tag_uuid]}),
            )


    # Test search with tag filter and q
    res = client.get(url_for("search") + f"?q={urls[2]}&tag={tag_name}", headers={'x-api-key': api_key, 'content-type': 'application/json'})
    assert len(res.json) == 1
    assert list(res.json.values())[0]['url'] == urls[2]

