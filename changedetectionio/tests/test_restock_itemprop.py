#!/usr/bin/env python3
import os
import time

from flask import url_for
from .util import live_server_setup, wait_for_all_checks, wait_for_notification_endpoint_output, extract_UUID_from_client
from ..notification import default_notification_format

instock_props = [
    # LD+JSON with non-standard list of 'type' https://github.com/dgtlmoon/changedetection.io/issues/1833
    '<script type=\'application/ld+json\'>{"@context": "http://schema.org","@type": ["Product", "SubType"],"name": "My test product","description":"","Offers": {    "@type": "Offer",    "offeredBy": {        "@type": "Organization",        "name":"Person",       "telephone":"+1 999 999 999"    },    "price": $$PRICE$$,    "priceCurrency": "EUR",    "url": "/some/url", "availability": "http://schema.org/InStock"}        }</script>',
    # LD JSON
    '<script id="product-jsonld" type="application/ld+json">{"@context":"https://schema.org","@type":"Product","brand":{"@type":"Brand","name":"Ubiquiti"},"name":"UniFi Express","sku":"UX","description":"Impressively compact UniFi Cloud Gateway and WiFi 6 access point that runs UniFi Network. Powers an entire network or simply meshes as an access point.","url":"https://store.ui.com/us/en/products/ux","image":{"@type":"ImageObject","url":"https://cdn.ecomm.ui.com/products/4ed25b4c-db92-4b98-bbf3-b0989f007c0e/123417a2-895e-49c7-ba04-b6cd8f6acc03.png","width":"1500","height":"1500"},"offers":{"@type":"Offer","availability":"https://schema.org/InStock","priceSpecification":{"@type":"PriceSpecification","price":$$PRICE$$,"priceCurrency":"USD","valueAddedTaxIncluded":false}}}</script>',
    '<script id="product-schema" type="application/ld+json">{"@context": "https://schema.org","@type": "Product","itemCondition": "https://schema.org/NewCondition","image": "//1.com/hmgo","name": "Polo MuscleFit","color": "Beige","description": "Polo","sku": "0957102010","brand": {"@type": "Brand","name": "H&M"},"category": {"@type": "Thing","name": "Polo"},"offers": [{"@type": "Offer","url": "https:/www2.xxxxxx.com/fr_fr/productpage.0957102010.html","priceCurrency": "EUR","price": $$PRICE$$,"availability": "http://schema.org/InStock","seller": {  "@type": "Organization", "name": "H&amp;M"}}]}</script>'
    # Microdata
    '<div itemscope itemtype="https://schema.org/Product"><h1 itemprop="name">Example Product</h1><p itemprop="description">This is a sample product description.</p><div itemprop="offers" itemscope itemtype="https://schema.org/Offer"><p>Price: <span itemprop="price">$$$PRICE$$</span></p><link itemprop="availability" href="https://schema.org/InStock" /></div></div>'
]

out_of_stock_props = [
    # out of stock AND contains multiples
    '<script type="application/ld+json">{"@context":"http://schema.org","@type":"WebSite","url":"https://www.medimops.de/","potentialAction":{"@type":"SearchAction","target":"https://www.medimops.de/produkte-C0/?fcIsSearch=1&searchparam={searchparam}","query-input":"required name=searchparam"}}</script><script type="application/ld+json">{"@context":"http://schema.org","@type":"Product","name":"Horsetrader: Robert Sangster and the Rise and Fall of the Sport of Kings","image":"https://images2.medimops.eu/product/43a982/M00002551322-large.jpg","productID":"isbn:9780002551328","gtin13":"9780002551328","category":"Livres en langue étrangère","offers":{"@type":"Offer","priceCurrency":"EUR","price":$$PRICE$$,"itemCondition":"UsedCondition","availability":"OutOfStock"},"brand":{"@type":"Thing","name":"Patrick Robinson","url":"https://www.momox-shop.fr/,patrick-robinson/"}}</script>'
]

def set_original_response(props_markup='', price="121.95"):

    props_markup=props_markup.replace('$$PRICE$$', price)
    test_return_data = f"""<html>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
     <div>price: ${price}</div>
     {props_markup}
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)
    time.sleep(1)
    return None




def test_setup(client, live_server):

    live_server_setup(live_server)

def test_restock_itemprop_basic(client, live_server):

    #live_server_setup(live_server)

    test_url = url_for('test_endpoint', _external=True)

    # By default it should enable ('in_stock_processing') == 'all_changes'

    for p in instock_props:
        set_original_response(props_markup=p)
        client.post(
            url_for("form_quick_watch_add"),
            data={"url": test_url, "tags": 'restock tests', 'processor': 'restock_diff'},
            follow_redirects=True
        )
        wait_for_all_checks(client)
        res = client.get(url_for("index"))
        assert b'more than one price detected' not in res.data
        assert b'has-restock-info' in res.data
        assert b' in-stock' in res.data
        assert b' not-in-stock' not in res.data
        res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
        assert b'Deleted' in res.data


    for p in out_of_stock_props:
        set_original_response(props_markup=p)
        client.post(
            url_for("form_quick_watch_add"),
            data={"url": test_url, "tags": '', 'processor': 'restock_diff'},
            follow_redirects=True
        )
        wait_for_all_checks(client)
        res = client.get(url_for("index"))

        assert b'has-restock-info not-in-stock' in res.data

        res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
        assert b'Deleted' in res.data

def test_itemprop_price_change(client, live_server):
    #live_server_setup(live_server)

    # Out of the box 'Follow price changes' should be ON
    test_url = url_for('test_endpoint', _external=True)

    set_original_response(props_markup=instock_props[0], price="190.95")
    client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url, "tags": 'restock tests', 'processor': 'restock_diff'},
        follow_redirects=True
    )

    # A change in price, should trigger a change by default
    wait_for_all_checks(client)
    res = client.get(url_for("index"))
    assert b'190.95' in res.data

    # basic price change, look for notification
    set_original_response(props_markup=instock_props[0], price='180.45')
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    res = client.get(url_for("index"))
    assert b'180.45' in res.data
    assert b'unviewed' in res.data
    client.get(url_for("mark_all_viewed"), follow_redirects=True)

    # turning off price change trigger, but it should show the new price, with no change notification
    set_original_response(props_markup=instock_props[0], price='120.45')
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"restock_settings-follow_price_changes": "", "url": test_url, "tags": "", "headers": "", 'fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    res = client.get(url_for("index"))
    assert b'120.45' in res.data
    assert b'unviewed' not in res.data


    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def _run_test_minmax_limit(client, extra_watch_edit_form):

    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

    test_url = url_for('test_endpoint', _external=True)

    set_original_response(props_markup=instock_props[0], price="950.95")
    client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url, "tags": 'restock tests', 'processor': 'restock_diff'},
        follow_redirects=True
    )
    wait_for_all_checks(client)

    data = {
        "tags": "",
        "url": test_url,
        "headers": "",
        "time_between_check-hours": 5,
        'fetch_backend': "html_requests"
    }
    data.update(extra_watch_edit_form)
    res = client.post(
        url_for("edit_page", uuid="first"),
        data=data,
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)

    client.get(url_for("mark_all_viewed"))

    # price changed to something greater than min (900), BUT less than max (1100).. should be no change
    set_original_response(props_markup=instock_props[0], price='1000.45')
    client.get(url_for("form_watch_checknow"))
    wait_for_all_checks(client)
    res = client.get(url_for("index"))

    assert b'more than one price detected' not in res.data
    # BUT the new price should show, even tho its within limits
    assert b'1,000.45' or b'1000.45' in res.data #depending on locale
    assert b'unviewed' not in res.data

    # price changed to something LESS than min (900), SHOULD be a change
    set_original_response(props_markup=instock_props[0], price='890.45')

    res = client.get(url_for("form_watch_checknow"), follow_redirects=True)
    assert b'1 watches queued for rechecking.' in res.data
    wait_for_all_checks(client)
    res = client.get(url_for("index"))
    assert b'890.45' in res.data
    assert b'unviewed' in res.data

    client.get(url_for("mark_all_viewed"))


    # 2715 - Price detection (once it crosses the "lower" threshold) again with a lower price - should trigger again!
    set_original_response(props_markup=instock_props[0], price='820.45')
    res = client.get(url_for("form_watch_checknow"), follow_redirects=True)
    assert b'1 watches queued for rechecking.' in res.data
    wait_for_all_checks(client)
    res = client.get(url_for("index"))
    assert b'820.45' in res.data
    assert b'unviewed' in res.data
    client.get(url_for("mark_all_viewed"))

    # price changed to something MORE than max (1100.10), SHOULD be a change
    set_original_response(props_markup=instock_props[0], price='1890.45')
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    res = client.get(url_for("index"))
    # Depending on the LOCALE it may be either of these (generally for US/default/etc)
    assert b'1,890.45' in res.data or b'1890.45' in res.data
    assert b'unviewed' in res.data

    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data


def test_restock_itemprop_minmax(client, live_server):
    #live_server_setup(live_server)
    extras = {
        "restock_settings-follow_price_changes": "y",
        "restock_settings-price_change_min": 900.0,
        "restock_settings-price_change_max": 1100.10
    }
    _run_test_minmax_limit(client, extra_watch_edit_form=extras)

def test_restock_itemprop_with_tag(client, live_server):
    #live_server_setup(live_server)

    res = client.post(
        url_for("tags.form_tag_add"),
        data={"name": "test-tag"},
        follow_redirects=True
    )
    assert b"Tag added" in res.data

    res = client.post(
        url_for("tags.form_tag_edit_submit", uuid="first"),
        data={"name": "test-tag",
              "restock_settings-follow_price_changes": "y",
              "restock_settings-price_change_min": 900.0,
              "restock_settings-price_change_max": 1100.10,
              "overrides_watch": "y", #overrides_watch should be restock_overrides_watch
              },
        follow_redirects=True
    )

    extras = {
        "tags": "test-tag"
    }

    _run_test_minmax_limit(client, extra_watch_edit_form=extras)



def test_itemprop_percent_threshold(client, live_server):
    #live_server_setup(live_server)

    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

    test_url = url_for('test_endpoint', _external=True)

    set_original_response(props_markup=instock_props[0], price="950.95")
    client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url, "tags": 'restock tests', 'processor': 'restock_diff'},
        follow_redirects=True
    )

    # A change in price, should trigger a change by default
    wait_for_all_checks(client)

    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"restock_settings-follow_price_changes": "y",
              "restock_settings-price_change_threshold_percent": 5.0,
              "url": test_url,
              "tags": "",
              "headers": "",
              'fetch_backend': "html_requests"
              },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)


    # Basic change should not trigger
    set_original_response(props_markup=instock_props[0], price='960.45')
    client.get(url_for("form_watch_checknow"))
    wait_for_all_checks(client)
    res = client.get(url_for("index"))
    assert b'960.45' in res.data
    assert b'unviewed' not in res.data

    # Bigger INCREASE change than the threshold should trigger
    set_original_response(props_markup=instock_props[0], price='1960.45')
    client.get(url_for("form_watch_checknow"))
    wait_for_all_checks(client)
    res = client.get(url_for("index"))
    assert b'1,960.45' or b'1960.45' in res.data #depending on locale
    assert b'unviewed' in res.data


    # Small decrease should NOT trigger
    client.get(url_for("mark_all_viewed"))
    set_original_response(props_markup=instock_props[0], price='1950.45')
    client.get(url_for("form_watch_checknow"))
    wait_for_all_checks(client)
    res = client.get(url_for("index"))
    assert b'1,950.45' or b'1950.45' in res.data #depending on locale
    assert b'unviewed' not in res.data




    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data



def test_change_with_notification_values(client, live_server):
    #live_server_setup(live_server)

    if os.path.isfile("test-datastore/notification.txt"):
        os.unlink("test-datastore/notification.txt")

    test_url = url_for('test_endpoint', _external=True)
    set_original_response(props_markup=instock_props[0], price='960.45')

    notification_url = url_for('test_notification_endpoint', _external=True).replace('http', 'json')

    ######################
    # You must add a type of 'restock_diff' for its tokens to register as valid in the global settings
    client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url, "tags": 'restock tests', 'processor': 'restock_diff'},
        follow_redirects=True
    )

    # A change in price, should trigger a change by default
    wait_for_all_checks(client)

    # Should see new tokens register
    res = client.get(url_for("settings_page"))
    assert b'{{restock.original_price}}' in res.data
    assert b'Original price at first check' in res.data

    #####################
    # Set this up for when we remove the notification from the watch, it should fallback with these details
    res = client.post(
        url_for("settings_page"),
        data={"application-notification_urls": notification_url,
              "application-notification_title": "title new price {{restock.price}}",
              "application-notification_body": "new price {{restock.price}}",
              "application-notification_format": default_notification_format,
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )

    # check tag accepts without error

    # Check the watches in these modes add the tokens for validating
    assert b"A variable or function is not defined" not in res.data

    assert b"Settings updated." in res.data


    set_original_response(props_markup=instock_props[0], price='960.45')
    # A change in price, should trigger a change by default
    set_original_response(props_markup=instock_props[0], price='1950.45')
    client.get(url_for("form_watch_checknow"))
    wait_for_all_checks(client)
    wait_for_notification_endpoint_output()
    assert os.path.isfile("test-datastore/notification.txt"), "Notification received"
    with open("test-datastore/notification.txt", 'r') as f:
        notification = f.read()
        assert "new price 1950.45" in notification
        assert "title new price 1950.45" in notification

    ## Now test the "SEND TEST NOTIFICATION" is working
    os.unlink("test-datastore/notification.txt")
    uuid = extract_UUID_from_client(client)
    res = client.post(url_for("ajax_callback_send_notification_test", watch_uuid=uuid), data={}, follow_redirects=True)
    time.sleep(5)
    assert os.path.isfile("test-datastore/notification.txt"), "Notification received"


def test_data_sanity(client, live_server):
    #live_server_setup(live_server)

    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

    test_url = url_for('test_endpoint', _external=True)
    test_url2 = url_for('test_endpoint2', _external=True)
    set_original_response(props_markup=instock_props[0], price="950.95")
    client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url, "tags": 'restock tests', 'processor': 'restock_diff'},
        follow_redirects=True
    )


    wait_for_all_checks(client)
    res = client.get(url_for("index"))
    assert b'950.95' in res.data

    # Check the restock model object doesnt store the value by mistake and used in a new one
    client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url2, "tags": 'restock tests', 'processor': 'restock_diff'},
        follow_redirects=True
    )
    wait_for_all_checks(client)
    res = client.get(url_for("index"))
    assert str(res.data.decode()).count("950.95") == 1, "Price should only show once (for the watch added, no other watches yet)"

    ## different test, check the edit page works on an empty request result
    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

    client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url2, "tags": 'restock tests', 'processor': 'restock_diff'},
        follow_redirects=True
    )
    wait_for_all_checks(client)

    res = client.get(
        url_for("edit_page", uuid="first"))
    assert test_url2.encode('utf-8') in res.data

    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

# All examples should give a prive of 666.66
def test_special_prop_examples(client, live_server):
    import glob
    #live_server_setup(live_server)

    test_url = url_for('test_endpoint', _external=True)
    check_path = os.path.join(os.path.dirname(__file__), "itemprop_test_examples", "*.txt")
    files = glob.glob(check_path)
    assert files
    for test_example_filename in files:
        with open(test_example_filename, 'r') as example_f:
            with open("test-datastore/endpoint-content.txt", "w") as test_f:
                test_f.write(f"<html><body>{example_f.read()}</body></html>")

            # Now fetch it and check the price worked
            client.post(
                url_for("form_quick_watch_add"),
                data={"url": test_url, "tags": 'restock tests', 'processor': 'restock_diff'},
                follow_redirects=True
            )
            wait_for_all_checks(client)
            res = client.get(url_for("index"))
            assert b'ception' not in res.data
            assert b'155.55' in res.data
