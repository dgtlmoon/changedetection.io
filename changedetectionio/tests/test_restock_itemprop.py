#!/usr/bin/python3
from flask import url_for
from .util import live_server_setup, wait_for_all_checks, extract_UUID_from_client

instock_props = [
    # LD+JSON with non-standard list of 'type' https://github.com/dgtlmoon/changedetection.io/issues/1833
    '<script type=\'application/ld+json\'>{"@context": "http://schema.org","@type": ["Product", "SubType"],"name": "My test product","description":"","Offers": {    "@type": "Offer",    "offeredBy": {        "@type": "Organization",        "name":"Person",       "telephone":"+1 999 999 999"    },    "price": $$PRICE$$,    "priceCurrency": "EUR",    "url": "/some/url", "availability": "http://schema.org/InStock"}        }</script>',
    # LD JSON
    '<script type=\'application/ld+json\'>[{"@context":"http://schema.org","@type":"WebSite","name":"partsDíly.cz","description":"Nejlevnější autodlíly.","url":"https://parts.com/?id=3038915","potentialAction":{"@type":"SearchAction","target":"https://parts.com/vyhledavani?search={query}","query-input":{"@type":"PropertyValueSpecification","valueRequired":"http://schema.org/True","valueName":"query"}},"publisher":{"@context":"http://schema.org","@type":"Organization","name":"Car Díly.cz","url":"https://carparts.com/","logo":"https://parts.com/77026_3195959275.png","sameAs":["https://twitter.com/parts","https://www.instagram.com/parts/?hl=cs"]},"sameAs":["https://twitter.com/parts","https://www.instagram.com/parts/"]},{"@context":"http://schema.org","@type":"BreadcrumbList","itemListElement":[{"@type":"ListItem","position":0,"item":{"@id":"/autodily","name":"Autodíly pro osobní vozy"}},{"@type":"ListItem","position":1,"item":{"@id":"/autodily/dodge","name":"DODGE"}},{"@type":"ListItem","position":2,"item":{"@id":"https://parts.com/280kw","name":"parts parts  • 100 kW"}}]},{"@context":"http://schema.org","@type":"Product","name":"Olejový filtr K&N Filters","description":"","mpn":"xxx11","brand":"K&N Filters","image":"https://parts.com/images/1600/c8fe1f1428021f4fe17a39297686178b04cba885.jpg","offers":{"@context":"http://schema.org","@type":"Offer","price":$$PRICE$$,"priceCurrency":"CZK","url":"https://parts.com/filters/hp","availability":"http://schema.org/InStock"}}]</script>',
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
    return None




def test_setup(client, live_server):

    live_server_setup(live_server)

def test_restock_itemprop_basic(client, live_server):

    #live_server_setup(live_server)

    test_url = url_for('test_endpoint', _external=True)

    for p in instock_props:
        set_original_response(props_markup=p)
        client.post(
            url_for("form_quick_watch_add"),
            data={"url": test_url, "tags": 'restock tests', 'processor': 'restock_diff'},
            follow_redirects=True
        )
        wait_for_all_checks(client)
        res = client.get(url_for("index"))
        assert b'has-restock-info in-stock' in res.data
        assert b'has-restock-info not-in-stock' not in res.data
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
#    live_server_setup(live_server)

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
        data={"follow_price_changes": "", "url": test_url, "tags": "", "headers": "", 'fetch_backend': "html_requests"},
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


def test_itemprop_price_minmax_limit(client, live_server):
    #live_server_setup(live_server)

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
        data={"follow_price_changes": "y",
              "price_change_min": 900.0,
              "price_change_max": 1100.10,
              "url": test_url,
              "tags": "",
              "headers": "",
              'fetch_backend': "html_requests"
              },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)

    client.get(url_for("mark_all_viewed"))

    # price changed to something greater than min (900), and less than max (1100).. should be no change
    set_original_response(props_markup=instock_props[0], price='1000.45')
    client.get(url_for("form_watch_checknow"))
    wait_for_all_checks(client)
    res = client.get(url_for("index"))
    assert b'1000.45' in res.data
    assert b'unviewed' not in res.data


    # price changed to something LESS than min (900), SHOULD be a change
    set_original_response(props_markup=instock_props[0], price='890.45')
    res = client.get(url_for("form_watch_checknow"), follow_redirects=True)
    assert b'1 watches queued for rechecking.' in res.data
    wait_for_all_checks(client)
    res = client.get(url_for("index"))
    assert b'890.45' in res.data
    assert b'unviewed' in res.data