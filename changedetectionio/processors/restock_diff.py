from . import difference_detection_processor
from ..html_tools import xpath1_filter as xpath_filter
# xpath1 is a lot faster and is sufficient here
from ..html_tools import extract_json_as_string, has_ldjson_product_info

from copy import deepcopy
from loguru import logger
import hashlib
import re
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

name = 'Re-stock detection for single product pages'
description = 'Detects if the product goes back to in-stock'


class UnableToExtractRestockData(Exception):
    def __init__(self, status_code):
        # Set this so we can use it in other parts of the app
        self.status_code = status_code
        return


def get_itemprop_availability(html_content):
    """
    `itemprop` is a global attribute
    https://developer.mozilla.org/en-US/docs/Web/HTML/Global_attributes/itemprop
    https://schema.org/ItemAvailability

    <div class="product-offer" itemprop="offers" itemscope="" itemtype="https://schema.org/Offer">
      ...
      <link itemprop="availability" href="https://schema.org/OutOfStock" />

    :return:
    """
    # Try/prefer the structured data first if it exists
    # https://schema.org/ItemAvailability Which strings mean we should consider it in stock?

    # Chewing on random content could throw any kind of exception, best to catch it and move on if possible.

    #LD-JSON type
    value = None
    try:
        if has_ldjson_product_info(html_content):
            value = extract_json_as_string(html_content.lower(), "json:$..offers.availability", ensure_is_ldjson_info_type=True)
            if value:
                value = re.sub(r'(?i)^(https|http)://schema.org/', '', value.strip(' "\''))
                logger.debug(f"Has 'LD-JSON' - '{value}'")

    except Exception as e:
        # This should be OK, we will attempt the scraped version instead
        logger.warning(f"Exception getting get_itemprop_availability 'LD-JSON' - {str(e)}")

    # Microdata style
    if not value:
        try:
            value = xpath_filter("//*[@itemtype='https://schema.org/Offer']//*[@itemprop='availability']/@href", html_content)
            if value:
                value = re.sub(r'(?i)^(https|http)://schema.org/', '', value.strip(' "\'').lower())
                logger.debug(f"Has 'Microdata' - '{value}'")

        except Exception as e:
            # This should be OK, we will attempt the scraped version instead
            logger.warning(f"Exception getting get_itemprop_availability 'Microdata' - {str(e)}")

    # RDFa style
    if not value:
        try:
            value = xpath_filter("//*[@property='schema:availability']/@content", html_content)
            if value:
                value = re.sub(r'(?i)^(https|http)://schema.org/', '', value.strip(' "\'').lower())
                logger.debug(f"Has 'RDFa' - '{value}'")

        except Exception as e:
            # This should be OK, we will attempt the scraped version instead
            logger.warning(f"Exception getting get_itemprop_availability 'RDFa' - {str(e)}")

    # @todo this should return dict/tuple of instock + price
    return value

class perform_site_check(difference_detection_processor):
    screenshot = None
    xpath_data = None


    def run_changedetection(self, uuid, skip_when_checksum_same=True):

        # DeepCopy so we can be sure we don't accidently change anything by reference
        watch = deepcopy(self.datastore.data['watching'].get(uuid))

        if not watch:
            raise Exception("Watch no longer exists.")

        # Unset any existing notification error
        update_obj = {'last_notification_error': False, 'last_error': False, 'in_stock': None}

        self.screenshot = self.fetcher.screenshot
        self.xpath_data = self.fetcher.xpath_data

        # Track the content type
        update_obj['content_type'] = self.fetcher.headers.get('Content-Type', '')
        update_obj["last_check_status"] = self.fetcher.get_last_status_code()

        availability = get_itemprop_availability(html_content=self.fetcher.content)

        if availability:
            self.fetcher.instock_data = availability # Stored as the text snapshot
            # @todo: Configurable?
            if any(availability in s for s in
                   [
                       'instock',
                       'Instoreonly',
                       'limitedavailability',
                       'onlineonly',
                       'presale'  # Debatable?
                   ]):
                update_obj['in_stock'] = True
            else:
                update_obj['in_stock'] = False

        # Fallback to scraping the content for keywords (done in JS)
        if update_obj['in_stock'] == None and self.fetcher.instock_data:
            # 'Possibly in stock' comes from stock-not-in-stock.js when no string found above the fold.
            update_obj['in_stock'] = True if self.fetcher.instock_data == 'Possibly in stock' else False
            logger.debug(f"Watch UUID {uuid} restock check returned '{self.fetcher.instock_data}' from JS scraper.")

        if not self.fetcher.instock_data:
            raise UnableToExtractRestockData(status_code=self.fetcher.status_code)

        # Main detection method
        fetched_md5 = None

        fetched_md5 = hashlib.md5(self.fetcher.instock_data.encode('utf-8')).hexdigest()

        # The main thing that all this at the moment comes down to :)
        changed_detected = False
        logger.debug(f"Watch UUID {uuid} restock check - Previous MD5: {watch.get('previous_md5')}, Fetched MD5 {fetched_md5}")

        if watch.get('in_stock') != update_obj.get('in_stock'):
            # Yes if we only care about it going to instock, AND we are in stock
            if watch.get('in_stock_only') and update_obj['in_stock']:
                changed_detected = True

            if not watch.get('in_stock_only'):
                # All cases
                changed_detected = True

        # Always record the new checksum
        update_obj["previous_md5"] = fetched_md5
        return changed_detected, update_obj, self.fetcher.instock_data.encode('utf-8').strip()

