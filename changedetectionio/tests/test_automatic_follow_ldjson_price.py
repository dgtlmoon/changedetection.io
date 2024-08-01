#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup, extract_UUID_from_client, extract_api_key_from_UI, wait_for_all_checks


def set_response_with_ldjson():
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
     <div class="sametext">Some text thats the same</div>
     <div class="changetext">Some text that will change</div>
     <script type="application/ld+json">
        {
           "@context":"https://schema.org/",
           "@type":"Product",
           "@id":"https://www.some-virtual-phone-shop.com/celular-iphone-14/p",
           "name":"Celular Iphone 14 Pro Max 256Gb E Sim A16 Bionic",
           "brand":{
              "@type":"Brand",
              "name":"APPLE"
           },
           "image":"https://www.some-virtual-phone-shop.com/15509426/image.jpg",
           "description":"You dont need it",
           "mpn":"111111",
           "sku":"22222",
           "Offers":{
              "@type":"AggregateOffer",
              "lowPrice":8097000,
              "highPrice":8099900,
              "priceCurrency":"COP",
              "offers":[
                 {
                    "@type":"Offer",
                    "price":8097000,
                    "priceCurrency":"COP",
                    "availability":"http://schema.org/InStock",
                    "sku":"102375961",
                    "itemCondition":"http://schema.org/NewCondition",
                    "seller":{
                       "@type":"Organization",
                       "name":"ajax"
                    }
                 }
              ],
              "offerCount":1
           }
        }
       </script>
     </body>
     </html>
"""

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)
    return None

def set_response_without_ldjson():
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
     <div class="sametext">Some text thats the same</div>
     <div class="changetext">Some text that will change</div>     
     </body>
     </html>
"""

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)
    return None

def test_setup(client, live_server, measure_memory_usage):
    live_server_setup(live_server)

# actually only really used by the distll.io importer, but could be handy too
def test_check_ldjson_price_autodetect(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)
    set_response_with_ldjson()

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    # Should get a notice that it's available
    res = client.get(url_for("index"))
    assert b'ldjson-price-track-offer' in res.data

    # Accept it
    uuid = extract_UUID_from_client(client)
    #time.sleep(1)
    client.get(url_for('price_data_follower.accept', uuid=uuid, follow_redirects=True))
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    # Offer should be gone
    res = client.get(url_for("index"))
    assert b'Embedded price data' not in res.data
    assert b'tracking-ldjson-price-data' in res.data

    # and last snapshop (via API) should be just the price
    api_key = extract_api_key_from_UI(client)
    res = client.get(
        url_for("watchsinglehistory", uuid=uuid, timestamp='latest'),
        headers={'x-api-key': api_key},
    )

    assert b'8097000' in res.data

    # And not this cause its not the ld-json
    assert b"So let's see what happens" not in res.data

    client.get(url_for("form_delete", uuid="all"), follow_redirects=True)

    ##########################################################################################
    # And we shouldnt see the offer
    set_response_without_ldjson()

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    wait_for_all_checks(client)
    res = client.get(url_for("index"))
    assert b'ldjson-price-track-offer' not in res.data
    
    ##########################################################################################
    client.get(url_for("form_delete", uuid="all"), follow_redirects=True)


def _test_runner_check_bad_format_ignored(live_server, client, has_ldjson_price_data):

    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    for k,v in client.application.config.get('DATASTORE').data['watching'].items():
        assert v.get('last_error') == False
        assert v.get('has_ldjson_price_data') == has_ldjson_price_data, f"Detected LDJSON data? should be {has_ldjson_price_data}"


    ##########################################################################################
    client.get(url_for("form_delete", uuid="all"), follow_redirects=True)


def test_bad_ldjson_is_correctly_ignored(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)
    test_return_data = """
            <html>
            <head>
                <script type="application/ld+json">
                    {
                        "@context": "http://schema.org",
                        "@type": ["Product", "SubType"],
                        "name": "My test product",
                        "description": "",
                        "offers": {
                            "note" : "You can see the case-insensitive OffERS key, it should work",
                            "@type": "Offer",
                            "offeredBy": {
                                "@type": "Organization",
                                "name":"Person",
                                "telephone":"+1 999 999 999"
                            },
                            "price": "1",
                            "priceCurrency": "EUR",
                            "url": "/some/url"
                        }
                    }
                </script>
            </head>
            <body>
            <div class="yes">Some extra stuff</div>
            </body></html>
     """
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)

    _test_runner_check_bad_format_ignored(live_server=live_server, client=client, has_ldjson_price_data=True)

    # This is OK that it offers a suggestion in this case, the processor will let them know more about something wrong

    # test_return_data = """
    #         <html>
    #         <head>
    #             <script type="application/ld+json">
    #                 {
    #                     "@context": "http://schema.org",
    #                     "@type": ["Product", "SubType"],
    #                     "name": "My test product",
    #                     "description": "",
    #                     "BrokenOffers": {
    #                         "@type": "Offer",
    #                         "offeredBy": {
    #                             "@type": "Organization",
    #                             "name":"Person",
    #                             "telephone":"+1 999 999 999"
    #                         },
    #                         "price": "1",
    #                         "priceCurrency": "EUR",
    #                         "url": "/some/url"
    #                     }
    #                 }
    #             </script>
    #         </head>
    #         <body>
    #         <div class="yes">Some extra stuff</div>
    #         </body></html>
    #  """
    # with open("test-datastore/endpoint-content.txt", "w") as f:
    #     f.write(test_return_data)
    #
    # _test_runner_check_bad_format_ignored(live_server=live_server, client=client, has_ldjson_price_data=False)
