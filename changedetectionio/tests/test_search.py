from flask import url_for


def test_basic_search(client, live_server, measure_memory_usage, datastore_path):
    
    uuidA = client.application.config.get('DATASTORE').add_watch(url='https://localhost:12300?first-result=1')
    uuidB = client.application.config.get('DATASTORE').add_watch(url='https://localhost:5000?second-result=1')


    # By URL
    res = client.get(url_for("watchlist.index") + "?q=first-res")
    assert uuidA.encode('utf-8') in res.data
    assert uuidB.encode('utf-8') not in res.data

    # By Title

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuidA),
        data={"title": "xxx-title", "url": 'https://localhost:12300?first-result=1', "tags": "", "headers": "", 'fetch_backend': "html_requests", "time_between_check_use_default": "y"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    res = client.get(url_for("watchlist.index") + "?q=xxx-title")
    assert uuidA.encode('utf-8') in res.data
    assert uuidB.encode('utf-8') not in res.data


def test_search_in_tag_limit(client, live_server, measure_memory_usage, datastore_path):

    uuidA = client.application.config.get('DATASTORE').add_watch(url='https://localhost:12300?first-result=1', tag='tag-one')
    uuidB = client.application.config.get('DATASTORE').add_watch(url='https://localhost:5000?second-result=1', tag='tag-two')

    # By URL

    res = client.get(url_for("watchlist.index") + "?q=first-res")

    assert 'tag-one'.encode('utf-8') in res.data
    # @todo filter from results?
    #assert 'tag-two'.encode('utf-8') not in res.data

    # By Title
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuidA),
        data={"title": "xxx-title", "url": 'https://localhost:12300?first-result=1', "tags": "tag-one", "headers": "",
              'fetch_backend': "html_requests", "time_between_check_use_default": "y"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    res = client.get(url_for("watchlist.index") + "?q=xxx-title")
    assert "tag-one".encode('utf-8') in res.data
    # @todo filter from results?
   # assert "tag-two".encode('utf-8') not in res.data

