from . import difference_detection_processor
from ..model import Restock
from copy import deepcopy
from loguru import logger
import hashlib
import re
import urllib3
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

    now = time.time()
    import extruct
    logger.trace(f"Imported extruct module in {time.time() - now:.3f}s")

    value = {}
    now = time.time()
    # Extruct is very slow, I'm wondering if some ML is going to be faster (800ms on my i7), 'rdfa' seems to be the heaviest.

    syntaxes = ['dublincore', 'json-ld', 'microdata', 'microformat', 'opengraph']

    data = extruct.extract(html_content, syntaxes=syntaxes)
    logger.trace(f"Extruct basic extract of all metadata done in {time.time() - now:.3f}s")

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


def is_between(number, lower=None, upper=None):
    """
    Check if a number is between two values.

    Parameters:
    number (float): The number to check.
    lower (float or None): The lower bound (inclusive). If None, no lower bound.
    upper (float or None): The upper bound (inclusive). If None, no upper bound.

    Returns:
    bool: True if the number is between the lower and upper bounds, False otherwise.
    """
    return (lower is None or lower <= number) and (upper is None or number <= upper)


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
        # Something valid in get_itemprop_availability() by scraping metadata ?
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
            update_obj['restock'] = Restock({'in_stock': True if self.fetcher.instock_data == 'Possibly in stock' else False})

            # @todo scrape price somehow
            logger.debug(
                f"Restock - using scraped browserdata - Watch UUID {uuid} restock check returned '{self.fetcher.instock_data}' from JS scraper.")

        if not self.fetcher.instock_data:
            raise UnableToExtractRestockData(status_code=self.fetcher.status_code)

        # Main detection method
        fetched_md5 = hashlib.md5(self.fetcher.instock_data.encode('utf-8')).hexdigest()

        # The main thing that all this at the moment comes down to :)
        changed_detected = False
        logger.debug(f"Watch UUID {uuid} restock check - Previous MD5: {watch.get('previous_md5')}, Fetched MD5 {fetched_md5}")

        # out of stock -> back in stock only?
        if watch.get('restock') and watch['restock'].get('in_stock') != update_obj['restock'].get('in_stock'):
            # Yes if we only care about it going to instock, AND we are in stock
            if watch.get('in_stock_only') and update_obj['restock']['in_stock']:
                changed_detected = True

            if not watch.get('in_stock_only'):
                # All cases
                changed_detected = True

        if watch.get('follow_price_changes') and watch.get('restock') and update_obj.get('restock') and update_obj['restock'].get('price'):
            price = float(update_obj['restock'].get('price'))
            # Default to current price if no previous price found
            previous_price = float(watch['restock'].get('price', price))

            # It was different, but negate it further down
            if price != previous_price:
                changed_detected = True

            # Minimum/maximum price limit
            if update_obj.get('restock') and update_obj['restock'].get('price'):
                logger.debug(
                    f"{uuid} - Change was detected, 'price_change_max' is '{watch.get('price_change_max', '')}' 'price_change_min' is '{watch.get('price_change_min', '')}', price from website is '{update_obj['restock'].get('price', '')}'.")
                if update_obj['restock'].get('price'):
                    min_limit = float(watch.get('price_change_min')) if watch.get('price_change_min') else None
                    max_limit = float(watch.get('price_change_max')) if watch.get('price_change_max') else None

                    price = float(update_obj['restock'].get('price'))
                    logger.debug(f"{uuid} after float conversion - Min limit: '{min_limit}' Max limit: '{max_limit}' Price: '{price}'")
                    if min_limit or max_limit:
                        if is_between(number=price, lower=min_limit, upper=max_limit):
                            if changed_detected:
                                logger.debug(f"{uuid} Override change-detected to FALSE because price was inside threshold")
                                changed_detected = False

                    if changed_detected and watch.get('price_change_threshold_percent'):
                        pc = float(watch.get('price_change_threshold_percent'))
                        change = abs((price - previous_price) / previous_price * 100)
                        if change and change <= pc:
                            logger.debug(f"{uuid} Override change-detected to FALSE because % threshold ({pc}%) was {change:.3f}%")
                            changed_detected = False
                        else:
                            logger.debug(f"{uuid} Price change was {change:.3f}% , (threshold {pc}%)")

        # Always record the new checksum
        update_obj["previous_md5"] = fetched_md5
        return changed_detected, update_obj, self.fetcher.instock_data.encode('utf-8').strip()
