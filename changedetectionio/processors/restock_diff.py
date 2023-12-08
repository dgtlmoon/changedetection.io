
import hashlib
import urllib3
from . import difference_detection_processor
from copy import deepcopy

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

name = 'Re-stock detection for single product pages'
description = 'Detects if the product goes back to in-stock'

class UnableToExtractRestockData(Exception):
    def __init__(self, status_code):
        # Set this so we can use it in other parts of the app
        self.status_code = status_code
        return

class perform_site_check(difference_detection_processor):
    screenshot = None
    xpath_data = None

    def get_itemprop_availability(self):
        from ..html_tools import xpath_filter
        import re
        # <link itemprop="availability" href="https://schema.org/OutOfStock" />
        # https://schema.org/ItemAvailability
        value = None
        try:
            value = xpath_filter("//link[@itemprop='availability']/@href", self.fetcher.content)
            if value:
                value = re.sub(r'(?i)^http(s)+://schema.org/', '', value.strip())

        except Exception as e:
            print("Exception getting get_itemprop_availability", str(e))

        return value


    def run_changedetection(self, uuid, skip_when_checksum_same=True):

        # DeepCopy so we can be sure we don't accidently change anything by reference
        watch = deepcopy(self.datastore.data['watching'].get(uuid))

        if not watch:
            raise Exception("Watch no longer exists.")

        # Unset any existing notification error
        update_obj = {'last_notification_error': False, 'last_error': False}

        self.screenshot = self.fetcher.screenshot
        self.xpath_data = self.fetcher.xpath_data

        # Track the content type
        update_obj['content_type'] = self.fetcher.headers.get('Content-Type', '')
        update_obj["last_check_status"] = self.fetcher.get_last_status_code()

        # Main detection method
        fetched_md5 = None

        # Try/prefer the structured data first if it exists
        # https://schema.org/ItemAvailability Which strings mean we should consider it in stock?
        availability = self.get_itemprop_availability()
        if availability:
            if any(availability in s for s in
                   [
                       'InStock',
                       'InStoreOnly',
                       'LimitedAvailability',
                       'OnlineOnly',
                       'PreSale' # Debatable?
                   ]):
                self.fetcher.instock_data = 'Possibly in stock'
            else:
                self.fetcher.instock_data = availability

        # Fallback to scraping the content for keywords (done in JS)
        if self.fetcher.instock_data:
            fetched_md5 = hashlib.md5(self.fetcher.instock_data.encode('utf-8')).hexdigest()
            # 'Possibly in stock' comes from stock-not-in-stock.js when no string found above the fold.
            update_obj["in_stock"] = True if self.fetcher.instock_data == 'Possibly in stock' else False
        else:
            raise UnableToExtractRestockData(status_code=self.fetcher.status_code)

        # The main thing that all this at the moment comes down to :)
        changed_detected = False

        if watch.get('previous_md5') and watch.get('previous_md5') != fetched_md5:
            # Yes if we only care about it going to instock, AND we are in stock
            if watch.get('in_stock_only') and update_obj["in_stock"]:
                changed_detected = True

            if not watch.get('in_stock_only'):
                # All cases
                changed_detected = True

        # Always record the new checksum
        update_obj["previous_md5"] = fetched_md5

        return changed_detected, update_obj, self.fetcher.instock_data.encode('utf-8')
