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
        """
        `itemprop` is a global attribute
        https://developer.mozilla.org/en-US/docs/Web/HTML/Global_attributes/itemprop
        https://schema.org/ItemAvailability

        <div class="product-offer" itemprop="offers" itemscope="" itemtype="https://schema.org/Offer">
          ...
          <link itemprop="availability" href="https://schema.org/OutOfStock" />

        :return:
        """
        from ..html_tools import xpath1_filter as xpath_filter
        # xpath1 is a lot faster and is sufficient here
        import re
        import time
        value = None
        try:
            value = xpath_filter("//*[@itemtype='https://schema.org/Offer']//*[@itemprop='availability']/@href", self.fetcher.content)
            if value:
                value = re.sub(r'(?i)^http(s)+://schema.org/', '', value.strip())

        except Exception as e:
            print("Exception getting get_itemprop_availability (itemprop='availability')", str(e))

        # Try RDFa style
        if not value:
            try:
                value = xpath_filter("//*[@property='schema:availability']/@content", self.fetcher.content)
                if value:
                    value = re.sub(r'(?i)^http(s)+://schema.org/', '', value.strip())

            except Exception as e:
                print("Exception getting get_itemprop_availability ('schema:availability')", str(e))

        return value

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

        # Main detection method
        fetched_md5 = None

        # Try/prefer the structured data first if it exists
        # https://schema.org/ItemAvailability Which strings mean we should consider it in stock?
        availability = self.get_itemprop_availability()
        if availability:
            self.fetcher.instock_data = availability
            if any(availability in s for s in
                   [
                       'InStock',
                       'InStoreOnly',
                       'LimitedAvailability',
                       'OnlineOnly',
                       'PreSale'  # Debatable?
                   ]):
                update_obj['in_stock'] = True
            else:
                update_obj['in_stock'] = False

        # Fallback to scraping the content for keywords (done in JS)
        if update_obj['in_stock'] == None and self.fetcher.instock_data:
            # 'Possibly in stock' comes from stock-not-in-stock.js when no string found above the fold.
            update_obj['in_stock'] = True if self.fetcher.instock_data == 'Possibly in stock' else False

        if update_obj['in_stock'] == None:
            raise UnableToExtractRestockData(status_code=self.fetcher.status_code)

        # The main thing that all this at the moment comes down to :)
        changed_detected = False

        if watch.get('in_stock') != update_obj.get('in_stock'):
            # Yes if we only care about it going to instock, AND we are in stock
            if watch.get('in_stock_only') and update_obj['in_stock']:
                changed_detected = True

            if not watch.get('in_stock_only'):
                # All cases
                changed_detected = True

        return changed_detected, update_obj, self.fetcher.instock_data.encode('utf-8')
