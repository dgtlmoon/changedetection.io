#!/usr/bin/env python3
import io
import os
import time

from flask import url_for

from .util import live_server_setup, wait_for_all_checks


def test_setup(client, live_server, measure_memory_usage):
    live_server_setup(live_server)

def test_import(client, live_server, measure_memory_usage):
    # Give the endpoint time to spin up
    wait_for_all_checks(client)

    res = client.post(
        url_for("import_page"),
        data={
            "distill-io": "",
            "urls": """https://example.com
https://example.com tag1
https://example.com tag1, other tag"""
        },
        follow_redirects=True,
    )
    assert b"3 Imported" in res.data
    assert b"tag1" in res.data
    assert b"other tag" in res.data
    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)

    # Clear flask alerts
    res = client.get( url_for("index"))
    res = client.get( url_for("index"))

def xtest_import_skip_url(client, live_server, measure_memory_usage):


    # Give the endpoint time to spin up
    time.sleep(1)

    res = client.post(
        url_for("import_page"),
        data={
            "distill-io": "",
            "urls": """https://example.com
:ht000000broken
"""
        },
        follow_redirects=True,
    )
    assert b"1 Imported" in res.data
    assert b"ht000000broken" in res.data
    assert b"1 Skipped" in res.data
    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    # Clear flask alerts
    res = client.get( url_for("index"))

def test_import_distillio(client, live_server, measure_memory_usage):

    distill_data='''
{
    "client": {
        "local": 1
    },
    "data": [
        {
            "name": "Unraid | News",
            "uri": "https://unraid.net/blog",
            "config": "{\\"selections\\":[{\\"frames\\":[{\\"index\\":0,\\"excludes\\":[],\\"includes\\":[{\\"type\\":\\"xpath\\",\\"expr\\":\\"(//div[@id='App']/div[contains(@class,'flex')]/main[contains(@class,'relative')]/section[contains(@class,'relative')]/div[@class='container']/div[contains(@class,'flex')]/div[contains(@class,'w-full')])[1]\\"}]}],\\"dynamic\\":true,\\"delay\\":2}],\\"ignoreEmptyText\\":true,\\"includeStyle\\":false,\\"dataAttr\\":\\"text\\"}",
            "tags": ["nice stuff", "nerd-news"],
            "content_type": 2,
            "state": 40,
            "schedule": "{\\"type\\":\\"INTERVAL\\",\\"params\\":{\\"interval\\":4447}}",
            "ts": "2022-03-27T15:51:15.667Z"
        }
    ]
}		   

'''

    # Give the endpoint time to spin up
    time.sleep(1)
    client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    res = client.post(
        url_for("import_page"),
        data={
            "distill-io": distill_data,
            "urls" : ''
        },
        follow_redirects=True,
    )


    assert b"Unable to read JSON file, was it broken?" not in res.data
    assert b"1 Imported from Distill.io" in res.data

    res = client.get( url_for("edit_page", uuid="first"))

    assert b"https://unraid.net/blog" in res.data
    assert b"Unraid | News" in res.data


    # flask/wtforms should recode this, check we see it
    # wtforms encodes it like id=&#39 ,but html.escape makes it like id=&#x27
    # - so just check it manually :(
    #import json
    #import html
    #d = json.loads(distill_data)
    # embedded_d=json.loads(d['data'][0]['config'])
    # x=html.escape(embedded_d['selections'][0]['frames'][0]['includes'][0]['expr']).encode('utf-8')
    assert b"xpath:(//div[@id=&#39;App&#39;]/div[contains(@class,&#39;flex&#39;)]/main[contains(@class,&#39;relative&#39;)]/section[contains(@class,&#39;relative&#39;)]/div[@class=&#39;container&#39;]/div[contains(@class,&#39;flex&#39;)]/div[contains(@class,&#39;w-full&#39;)])[1]" in res.data

    # did the tags work?
    res = client.get( url_for("index"))

    # check tags
    assert b"nice stuff" in res.data
    assert b"nerd-news" in res.data

    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    # Clear flask alerts
    res = client.get(url_for("index"))

def test_import_custom_xlsx(client, live_server, measure_memory_usage):
    """Test can upload a excel spreadsheet and the watches are created correctly"""

    #live_server_setup(live_server)

    dirname = os.path.dirname(__file__)
    filename = os.path.join(dirname, 'import/spreadsheet.xlsx')
    with open(filename, 'rb') as f:

        data= {
            'file_mapping': 'custom',
            'custom_xlsx[col_0]': '1',
            'custom_xlsx[col_1]': '3',
            'custom_xlsx[col_2]': '5',
            'custom_xlsx[col_3]': '4',
            'custom_xlsx[col_type_0]': 'title',
            'custom_xlsx[col_type_1]': 'url',
            'custom_xlsx[col_type_2]': 'include_filters',
            'custom_xlsx[col_type_3]': 'interval_minutes',
            'xlsx_file': (io.BytesIO(f.read()), 'spreadsheet.xlsx')
        }

    res = client.post(
        url_for("import_page"),
        data=data,
        follow_redirects=True,
    )

    assert b'4 imported from custom .xlsx' in res.data
    # Because this row was actually just a header with no usable URL, we should get an error
    assert b'Error processing row number 1' in res.data

    res = client.get(
        url_for("index")
    )

    assert b'Somesite results ABC' in res.data
    assert b'City news results' in res.data

    # Just find one to check over
    for uuid, watch in live_server.app.config['DATASTORE'].data['watching'].items():
        if watch.get('title') == 'Somesite results ABC':
            filters = watch.get('include_filters')
            assert filters[0] == '/html[1]/body[1]/div[4]/div[1]/div[1]/div[1]||//*[@id=\'content\']/div[3]/div[1]/div[1]||//*[@id=\'content\']/div[1]'
            assert watch.get('time_between_check') == {'weeks': 0, 'days': 1, 'hours': 6, 'minutes': 24, 'seconds': 0}

    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_import_watchete_xlsx(client, live_server, measure_memory_usage):
    """Test can upload a excel spreadsheet and the watches are created correctly"""

    #live_server_setup(live_server)
    dirname = os.path.dirname(__file__)
    filename = os.path.join(dirname, 'import/spreadsheet.xlsx')
    with open(filename, 'rb') as f:

        data= {
            'file_mapping': 'wachete',
            'xlsx_file': (io.BytesIO(f.read()), 'spreadsheet.xlsx')
        }

    res = client.post(
        url_for("import_page"),
        data=data,
        follow_redirects=True,
    )

    assert b'4 imported from Wachete .xlsx' in res.data

    res = client.get(
        url_for("index")
    )

    assert b'Somesite results ABC' in res.data
    assert b'City news results' in res.data

    # Just find one to check over
    for uuid, watch in live_server.app.config['DATASTORE'].data['watching'].items():
        if watch.get('title') == 'Somesite results ABC':
            filters = watch.get('include_filters')
            assert filters[0] == '/html[1]/body[1]/div[4]/div[1]/div[1]/div[1]||//*[@id=\'content\']/div[3]/div[1]/div[1]||//*[@id=\'content\']/div[1]'
            assert watch.get('time_between_check') == {'weeks': 0, 'days': 1, 'hours': 6, 'minutes': 24, 'seconds': 0}
            assert watch.get('fetch_backend') == 'html_requests' # Has inactive 'dynamic wachet'

        if watch.get('title') == 'JS website':
            assert watch.get('fetch_backend') == 'html_webdriver' # Has active 'dynamic wachet'

        if watch.get('title') == 'system default website':
            assert watch.get('fetch_backend') == 'system' # uses default if blank

    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data
