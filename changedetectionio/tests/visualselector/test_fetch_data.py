#!/usr/bin/env python3

import os
from flask import url_for
from ..util import live_server_setup, wait_for_all_checks

# def test_setup(client, live_server, measure_memory_usage, datastore_path):
   #  live_server_setup(live_server) # Setup on conftest per function


# Add a site in paused mode, add an invalid filter, we should still have visual selector data ready
def test_visual_selector_content_ready(client, live_server, measure_memory_usage, datastore_path):

    import os
    import json

    assert os.getenv('PLAYWRIGHT_DRIVER_URL'), "Needs PLAYWRIGHT_DRIVER_URL set for this test"

    # Add our URL to the import page, because the docker container (playwright/selenium) wont be able to connect to our usual test url
    test_url = url_for('test_interactive_html_endpoint', _external=True)
    test_url = test_url.replace('localhost.localdomain', 'cdio')
    test_url = test_url.replace('localhost', 'cdio')

    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": '', 'edit_and_watch_submit_button': 'Edit > Watch'},
        follow_redirects=True
    )
    assert b"Watch added in Paused state, saving will unpause" in res.data
    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid, unpause_on_save=1),
        data={
            "url": test_url,
            "tags": "",
            # For now, cookies doesnt work in headers because it must be a full cookiejar object
            'headers': "testheader: yes\buser-agent: MyCustomAgent",
            'fetch_backend': "html_webdriver",
            "time_between_check_use_default": "y",
        },
        follow_redirects=True
    )
    assert b"unpaused" in res.data
    wait_for_all_checks(client)


    assert live_server.app.config['DATASTORE'].data['watching'][uuid].history_n >= 1, "Watch history had atleast 1 (everything fetched OK)"

    res = client.get(
        url_for("ui.ui_preview.preview_page", uuid=uuid),
        follow_redirects=True
    )
    assert b"testheader: yes" in res.data
    assert b"user-agent: mycustomagent" in res.data


    assert os.path.isfile(os.path.join(datastore_path, uuid, 'last-screenshot.png')), "last-screenshot.png should exist"
    assert os.path.isfile(os.path.join(datastore_path, uuid, 'elements.deflate')), "xpath elements.deflate data should exist"

    # Open it and see if it roughly looks correct
    with open(os.path.join(datastore_path, uuid, 'elements.deflate'), 'rb') as f:
        import zlib
        compressed_data = f.read()
        decompressed_data = zlib.decompress(compressed_data)
        # See if any error was thrown
        json_data = json.loads(decompressed_data.decode('utf-8'))

    # Attempt to fetch it via the web hook that the browser would use
    res = client.get(url_for('static_content', group='visual_selector_data', filename=uuid))
    decompressed_data = zlib.decompress(res.data)
    json_data = json.loads(decompressed_data.decode('utf-8'))
    
    assert res.mimetype == 'application/json'
    assert res.status_code == 200


    # Some options should be enabled
    # @todo - in the future, the visibility should be toggled by JS from the request type setting
    res = client.get(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        follow_redirects=True
    )
    assert b'notification_screenshot' in res.data
    client.get(
        url_for("ui.form_delete", uuid="all"),
        follow_redirects=True
    )

def test_basic_browserstep(client, live_server, measure_memory_usage, datastore_path):


    test_url = url_for('test_interactive_html_endpoint', _external=True)
    test_url = test_url.replace('localhost.localdomain', 'cdio')
    test_url = test_url.replace('localhost', 'cdio')

    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": '', 'edit_and_watch_submit_button': 'Edit > Watch'},
        follow_redirects=True
    )

    assert b"Watch added in Paused state, saving will unpause" in res.data

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first", unpause_on_save=1),
        data={
            "url": test_url,
            "tags": "",
            'fetch_backend': "html_webdriver",
            'browser_steps-5-operation': 'Enter text in field',
            'browser_steps-5-selector': '#test-input-text',
            # Should get set to the actual text (jinja2 rendered)
            'browser_steps-5-optional_value': "Hello-Jinja2-{% now  'Europe/Berlin', '%Y-%m-%d' %}",
            'browser_steps-8-operation': 'Click element',
            'browser_steps-8-selector': 'button[name=test-button]',
            'browser_steps-8-optional_value': '',
            # For now, cookies doesnt work in headers because it must be a full cookiejar object
            'headers': "testheader: yes\buser-agent: MyCustomAgent",
            "time_between_check_use_default": "y",
        },
        follow_redirects=True
    )
    assert b"unpaused" in res.data

    wait_for_all_checks(client)
    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))

    # 3874 - should have tidied up any blanks
    watch = live_server.app.config['DATASTORE'].data['watching'][uuid]
    assert watch['browser_steps'][0].get('operation') == 'Enter text in field'
    assert watch['browser_steps'][1].get('selector') == 'button[name=test-button]'


    # This part actually needs the browser, before this we are just testing data
    assert os.getenv('PLAYWRIGHT_DRIVER_URL'), "Needs PLAYWRIGHT_DRIVER_URL set for this test"
    assert live_server.app.config['DATASTORE'].data['watching'][uuid].history_n >= 1, "Watch history had atleast 1 (everything fetched OK)"

    assert b"This text should be removed" not in res.data

    # Check HTML conversion detected and workd
    res = client.get(
        url_for("ui.ui_preview.preview_page", uuid=uuid),
        follow_redirects=True
    )
    assert b"This text should be removed" not in res.data
    assert b"I smell JavaScript because the button was pressed" in res.data

    assert b'Hello-Jinja2-20' in res.data

    assert b"testheader: yes" in res.data
    assert b"user-agent: mycustomagent" in res.data

def test_non_200_errors_report_browsersteps(client, live_server, measure_memory_usage, datastore_path):

    four_o_four_url =  url_for('test_endpoint', status_code=404, _external=True)
    four_o_four_url = four_o_four_url.replace('localhost.localdomain', 'cdio')
    four_o_four_url = four_o_four_url.replace('localhost', 'cdio')

    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": four_o_four_url, "tags": '', 'edit_and_watch_submit_button': 'Edit > Watch'},
        follow_redirects=True
    )

    assert b"Watch added in Paused state, saving will unpause" in res.data
    assert os.getenv('PLAYWRIGHT_DRIVER_URL'), "Needs PLAYWRIGHT_DRIVER_URL set for this test"

    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))

    # now test for 404 errors
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid, unpause_on_save=1),
        data={
              "url": four_o_four_url,
              "tags": "",
              'fetch_backend': "html_webdriver",
              'browser_steps-0-operation': 'Click element',
              'browser_steps-0-selector': 'button[name=test-button]',
              'browser_steps-0-optional_value': '',
              "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )
    assert b"unpaused" in res.data

    wait_for_all_checks(client)

    res = client.get(url_for("watchlist.index"))

    assert b'Error - 404' in res.data

    client.get(
        url_for("ui.form_delete", uuid="all"),
        follow_redirects=True
    )

def test_browsersteps_edit_UI_startsession(client, live_server, measure_memory_usage, datastore_path):

    assert os.getenv('PLAYWRIGHT_DRIVER_URL'), "Needs PLAYWRIGHT_DRIVER_URL set for this test"

    # Add a watch first
    test_url = url_for('test_interactive_html_endpoint', _external=True)
    test_url = test_url.replace('localhost.localdomain', 'cdio')
    test_url = test_url.replace('localhost', 'cdio')

    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url, extras={'fetch_backend': 'html_webdriver', 'paused': True})

    # Test starting a browsersteps session
    res = client.get(
        url_for("browser_steps.browsersteps_start_session", uuid=uuid),
        follow_redirects=True
    )

    assert res.status_code == 200
    assert res.is_json
    json_data = res.get_json()
    assert 'browsersteps_session_id' in json_data
    assert json_data['browsersteps_session_id']  # Not empty

    browsersteps_session_id = json_data['browsersteps_session_id']

    # Verify the session exists in browsersteps_sessions
    from changedetectionio.blueprint.browser_steps import browsersteps_sessions, browsersteps_watch_to_session
    assert browsersteps_session_id in browsersteps_sessions
    assert uuid in browsersteps_watch_to_session
    assert browsersteps_watch_to_session[uuid] == browsersteps_session_id

    # Verify browsersteps UI shows up on edit page
    res = client.get(url_for("ui.ui_edit.edit_page", uuid=uuid))
    assert b'browsersteps-click-start' in res.data, "Browsersteps manual UI shows up"

    # Session should still exist after GET (not cleaned up yet)
    assert browsersteps_session_id in browsersteps_sessions
    assert uuid in browsersteps_watch_to_session

    # Test cleanup happens on save (POST)
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data={
            "url": test_url,
            "tags": "",
            'fetch_backend': "html_webdriver",
            "time_between_check_use_default": "y",
        },
        follow_redirects=True
    )
    assert b"Updated watch" in res.data

    # NOW verify the session was cleaned up after save
    assert browsersteps_session_id not in browsersteps_sessions
    assert uuid not in browsersteps_watch_to_session

    # Cleanup
    client.get(
        url_for("ui.form_delete", uuid="all"),
        follow_redirects=True
    )
