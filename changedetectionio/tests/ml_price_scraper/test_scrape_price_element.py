import os

from flask import url_for
from changedetectionio.tests.util import set_original_response, set_modified_response, set_more_modified_response, live_server_setup, \
    wait_for_all_checks, \
    set_longer_modified_response

import time

# No semantic data just some text, we should be able to find the product price.
def set_response(price="121.95"):
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Ajax Widget</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 0;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                background-color: #f4f4f4;
            }}
            .container {{
                display: flex;
                flex-direction: row;
                background-color: #fff;
                border: 1px solid #ddd;
                padding: 20px;
                border-radius: 5px;
                box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
                width: 80%;
                max-width: 800px;
            }}
            .description {{
                flex: 2;
                margin-right: 20px;
            }}
            .description h1 {{
                margin-top: 0;
            }}
            .price {{
                flex: 1;
                text-align: right;
                font-size: 24px;
                color: #333;
            }}
            .price span {{
                font-size: 32px;
                font-weight: bold;
            }}
            .buy-button {{
                display: inline-block;
                margin-top: 20px;
                padding: 10px 20px;
                background-color: #28a745;
                color: #fff;
                text-decoration: none;
                border-radius: 5px;
                font-size: 16px;
            }}
            .buy-button:hover {{
                background-color: #218838;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="description">
                <h1>Ajax Widget</h1>
                <p>The Ajax Widget is the ultimate solution for all your widget needs. Crafted with precision and using the latest technology, this widget offers unmatched performance and durability. Whether you're using it for personal or professional purposes, the Ajax Widget will not disappoint. It's easy to use, reliable, and comes with a sleek design that complements any setup. Don't settle for less; get the best with the Ajax Widget today!</p>
            </div>
            <div class="price">
                <span>${price}</span>
                <br>
                <a href="#" class="buy-button">Buy Now</a><br>
                IN STOCK
            </div>
        </div>
    </body>
    </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(html_content)
    time.sleep(1)
    return None




def test_restock_itemprop_basic(client, live_server):

    # needs to be set and something like 'ws://127.0.0.1:3000'
    assert os.getenv('PLAYWRIGHT_DRIVER_URL'), "Needs PLAYWRIGHT_DRIVER_URL set for this test"
    assert os.getenv('PRICE_SCRAPER_ML_ENDPOINT'), "Needs PRICE_SCRAPER_ML_ENDPOINT set for this test"


    live_server_setup(live_server)

    set_response(price="123.99")

    test_url = url_for('test_endpoint', _external=True)

    client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url, "tags": 'restock tests', 'processor': 'restock_diff'},
        follow_redirects=True
    )
    wait_for_all_checks(client)
    res = client.get(url_for("index"))

    assert b'123.99' in res.data
    assert b' in-stock' in res.data
    assert b' not-in-stock' not in res.data

    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data
