from . import difference_detection_processor
from ..html_tools import xpath1_filter as xpath_filter
# xpath1 is a lot faster and is sufficient here
from ..html_tools import extract_json_as_string, has_ldjson_product_info
from ..model import Restock
from copy import deepcopy
from loguru import logger
import hashlib
import re
import urllib3
import extruct
import time

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

name = 'Re-stock & Price detection for single product pages'
description = 'Detects if the product goes back to in-stock'


class UnableToExtractRestockData(Exception):
    def __init__(self, status_code):
        # Set this so we can use it in other parts of the app
        self.status_code = status_code
        return

def _search_prop_by_value(matches, value):
    for properties in matches:
        for prop in properties:
            if value in prop[0]:
                return prop[1]  # Yield the desired value and exit the function

# should return Restock()
# add casting?
def get_itemprop_availability(html_content) -> Restock:
    """
    Kind of funny/cool way to find price/availability in one many different possibilities.
    Use 'extruct' to find any possible RDFa/microdata/json-ld data, make a JSON string from the output then search it.
    """
    from jsonpath_ng import parse

    value={}

    now = time.time()
    data = extruct.extract(html_content)

    # First phase, dead simple scanning of anything that looks useful
    if data:
        logger.debug(f"Using jsonpath to find price/availability/etc")
        price_parse = parse('$..(price|Price)')
        pricecurrency_parse = parse('$..(pricecurrency|currency| priceCurrency )')
        availability_parse = parse('$..(availability|Availability)')

        price_result = price_parse.find(data)
        if price_result:
            value['price'] = price_result[0].value

        pricecurrency_result = pricecurrency_parse.find(data)
        if pricecurrency_result:
            value['currency'] = pricecurrency_result[0].value

        availability_result = availability_parse.find(data)
        if availability_result:
            value['availability'] = availability_result[0].value

        if value.get('availability'):
            value['availability'] = re.sub(r'(?i)^(https|http)://schema.org/', '',
                                           value.get('availability').strip(' "\'').lower()) if value.get('availability') else None

        # Second, go dig OpenGraph which is something that jsonpath_ng cant do because of the tuples and double-dots (:)
        if not value.get('price') or value.get('availability'):
            logger.debug(f"Alternatively digging through OpenGraph properties for restock/price info..")
            jsonpath_expr = parse('$..properties')

            for match in jsonpath_expr.find(data):
                if not value.get('price'):
                    value['price'] = _search_prop_by_value([match.value], "price:amount")
                if not value.get('availability'):
                    value['availability'] = _search_prop_by_value([match.value], "product:availability")
                if not value.get('currency'):
                    value['currency'] = _search_prop_by_value([match.value], "price:currency")

    logger.trace(f"Processed with Extruct in {time.time()-now:.3f}s")

    return Restock(value)

class perform_site_check(difference_detection_processor):
    screenshot = None
    xpath_data = None


    def run_changedetection(self, uuid, skip_when_checksum_same=True):

        # DeepCopy so we can be sure we don't accidently change anything by reference
        watch = deepcopy(self.datastore.data['watching'].get(uuid))

        if not watch:
            raise Exception("Watch no longer exists.")

        # Unset any existing notification error
        update_obj = {'last_notification_error': False, 'last_error': False, 'restock':  None}

        self.screenshot = self.fetcher.screenshot
        self.xpath_data = self.fetcher.xpath_data

        # Track the content type
        update_obj['content_type'] = self.fetcher.headers.get('Content-Type', '')
        update_obj["last_check_status"] = self.fetcher.get_last_status_code()

        itemprop_availability = get_itemprop_availability(html_content=self.fetcher.content)
        if itemprop_availability.get('price') or itemprop_availability.get('availability'):
            # Store for other usage
            update_obj['restock'] = itemprop_availability

            if itemprop_availability.get('availability'):
                # @todo: Configurable?
                if any(substring.lower() in itemprop_availability['availability'].lower() for substring in [
                    'instock',
                    'instoreonly',
                    'limitedavailability',
                    'onlineonly',
                    'presale']
                       ):
                    update_obj['restock']['in_stock'] = True
                else:
                    update_obj['restock']['in_stock'] = False

            # Used for the change detection, we store the real data separately, in the future this can implement some min,max threshold
            # @todo if price is None?
            self.fetcher.instock_data = f"{itemprop_availability.get('availability')} - {itemprop_availability.get('price')}"

        elif self.fetcher.instock_data:
            # 'Possibly in stock' comes from stock-not-in-stock.js when no string found above in the metadata of the HTML
            update_obj['restock']['in_stock'] = True if self.fetcher.instock_data == 'Possibly in stock' else False
            logger.debug(f"Restock - using scraped browserdata - Watch UUID {uuid} restock check returned '{self.fetcher.instock_data}' from JS scraper.")

        if not self.fetcher.instock_data:
            raise UnableToExtractRestockData(status_code=self.fetcher.status_code)

        # Main detection method
        fetched_md5 = hashlib.md5(self.fetcher.instock_data.encode('utf-8')).hexdigest()

        # The main thing that all this at the moment comes down to :)
        changed_detected = False
        logger.debug(f"Watch UUID {uuid} restock check - Previous MD5: {watch.get('previous_md5')}, Fetched MD5 {fetched_md5}")

        if watch['restock'].get('in_stock') != update_obj['restock'].get('in_stock'):
            # Yes if we only care about it going to instock, AND we are in stock
            if watch.get('in_stock_only') and update_obj['restock']['in_stock']:
                changed_detected = True

            if not watch.get('in_stock_only'):
                # All cases
                changed_detected = True

        # Always record the new checksum
        update_obj["previous_md5"] = fetched_md5
        return changed_detected, update_obj, self.fetcher.instock_data.encode('utf-8').strip()
