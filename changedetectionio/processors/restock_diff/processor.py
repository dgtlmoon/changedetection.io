from ..base import difference_detection_processor
from ..exceptions import ProcessorException
from . import Restock
from loguru import logger
from changedetectionio.content_fetchers.exceptions import checksumFromPreviousCheckWasTheSame

import urllib3
import time

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# Translatable strings - extracted by pybabel, translated at runtime in __init__.py
# Use a marker function so pybabel can extract these strings
def _(x): return x  # Translation marker for extraction only
name = _('Re-stock & Price detection for pages with a SINGLE product')
description = _('Detects if the product goes back to in-stock')
del _  # Remove marker function
processor_weight = 1
list_badge_text = "Restock"  # _()

class UnableToExtractRestockData(Exception):
    def __init__(self, status_code):
        # Set this so we can use it in other parts of the app
        self.status_code = status_code
        return

class MoreThanOnePriceFound(Exception):
    def __init__(self):
        return

def _search_prop_by_value(matches, value):
    for properties in matches:
        for prop in properties:
            if value in prop[0]:
                return prop[1]  # Yield the desired value and exit the function

def _deduplicate_prices(data):
    import re

    '''
    Some price data has multiple entries, OR it has a single entry with ['$159', '159', 159, "$ 159"] or just "159"
    Get all the values, clean it and add it to a set then return the unique values
    '''
    unique_data = set()

    # Return the complete 'datum' where its price was not seen before
    for datum in data:

        if isinstance(datum.value, list):
            # Process each item in the list
            normalized_value = set([float(re.sub(r'[^\d.]', '', str(item))) for item in datum.value if str(item).strip()])
            unique_data.update(normalized_value)
        else:
            # Process single value
            v = float(re.sub(r'[^\d.]', '', str(datum.value)))
            unique_data.add(v)

    return list(unique_data)


# =============================================================================
# MEMORY MANAGEMENT: Why We Use Multiprocessing (Linux Only)
# =============================================================================
#
# The get_itemprop_availability() function uses 'extruct' to parse HTML metadata
# (JSON-LD, microdata, OpenGraph, etc). Extruct internally uses lxml, which wraps
# libxml2 - a C library that allocates memory at the C level.
#
# Memory Leak Problem:
# --------------------
# 1. lxml's document_fromstring() creates thousands of Python objects backed by
#    C-level allocations (nodes, attributes, text content)
# 2. Python's garbage collector can mark these objects as collectible, but
#    cannot force the OS to reclaim the actual C-level memory
# 3. malloc/free typically doesn't return memory to OS - it just marks it as
#    "free in the process address space"
# 4. With repeated parsing of large HTML (5MB+ pages), memory accumulates even
#    after Python GC runs
#
# Why Multiprocessing Fixes This:
# --------------------------------
# When a subprocess exits, the OS forcibly reclaims ALL memory including C-level
# allocations that Python GC couldn't release. This ensures clean memory state
# after each extraction.
#
# Performance Impact:
# -------------------
# - Memray analysis showed 1.2M document_fromstring allocations per page
# - Without subprocess: memory grows by ~50-500MB per parse and lingers
# - With subprocess: ~35MB overhead but forces full cleanup after each run
# - Trade-off: 35MB resource_tracker vs 500MB+ accumulated leak = much better at scale
#
# References:
# -----------
# - lxml memory issues: https://medium.com/devopss-hole/python-lxml-memory-leak-b8d0b1000dc7
# - libxml2 caching behavior: https://www.mail-archive.com/lxml@python.org/msg00026.html
# - GC limitations with C extensions: https://benbernardblog.com/tracking-down-a-freaky-python-memory-leak-part-2/
#
# Additional Context:
# -------------------
# - jsonpath_ng (used to query the parsed data) is pure Python and doesn't leak
# - The leak is specifically from lxml's document parsing, not the JSONPath queries
# - Linux-only because multiprocessing spawn is well-tested there; other platforms
#   use direct call as fallback
#
# Alternative Solution (Future Optimization):
# -------------------------------------------
# This entire problem could be avoided by using regex to extract just the machine
# data blocks (JSON-LD, microdata, OpenGraph tags) BEFORE parsing with lxml:
#
#   1. Use regex to extract <script type="application/ld+json">...</script> blocks
#   2. Use regex to extract <meta property="og:*"> tags
#   3. Use regex to find itemprop/itemtype attributes and their containing elements
#   4. Parse ONLY those extracted snippets instead of the entire HTML document
#
# Benefits:
#   - Avoids parsing 5MB of HTML when we only need a few KB of metadata
#   - Eliminates the lxml memory leak entirely
#   - Faster extraction (regex is much faster than DOM parsing)
#   - No subprocess overhead needed
#
# Trade-offs:
#   - Regex for HTML is brittle (comments, CDATA, edge cases)
#   - Microdata extraction would be complex (need to track element boundaries)
#   - Would need extensive testing to ensure we don't miss valid data
#   - extruct is battle-tested; regex solution would need similar maturity
#
# For now, the subprocess approach is safer and leverages existing extruct code.
# =============================================================================


def _extract_itemprop_availability_worker(pipe_conn):
    """
    Subprocess worker for itemprop extraction (Linux memory management).

    Uses spawn multiprocessing to isolate extruct/lxml memory allocations.
    When the subprocess exits, the OS reclaims ALL memory including lxml's
    C-level allocations that Python's GC cannot release.

    Args:
        pipe_conn: Pipe connection to receive HTML and send result
    """
    import json
    import gc

    html_content = None
    result_data = None

    try:
        # Receive HTML as raw bytes (no pickle)
        html_bytes = pipe_conn.recv_bytes()
        html_content = html_bytes.decode('utf-8')

        # Explicitly delete html_bytes to free memory
        del html_bytes
        gc.collect()

        # Perform extraction in subprocess (uses extruct/lxml)
        result_data = get_itemprop_availability(html_content)

        # Convert Restock object to dict for JSON serialization
        result = {
            'success': True,
            'data': dict(result_data) if result_data else {}
        }
        pipe_conn.send_bytes(json.dumps(result).encode('utf-8'))

        # Clean up before exit
        del result_data, html_content, result
        gc.collect()

    except MoreThanOnePriceFound:
        # Serialize the specific exception type
        result = {
            'success': False,
            'exception_type': 'MoreThanOnePriceFound'
        }
        pipe_conn.send_bytes(json.dumps(result).encode('utf-8'))

    except Exception as e:
        # Serialize other exceptions
        result = {
            'success': False,
            'exception_type': type(e).__name__,
            'exception_message': str(e)
        }
        pipe_conn.send_bytes(json.dumps(result).encode('utf-8'))

    finally:
        # Final cleanup before subprocess exits
        # Variables may already be deleted in try block, so use try/except
        try:
            del html_content
        except (NameError, UnboundLocalError):
            pass
        try:
            del result_data
        except (NameError, UnboundLocalError):
            pass
        gc.collect()
        pipe_conn.close()


def extract_itemprop_availability_safe(html_content) -> Restock:
    """
    Extract itemprop availability with hybrid approach for memory efficiency.

    Strategy (fastest to slowest, least to most memory):
    1. Try pure Python extraction (JSON-LD, OpenGraph, microdata) - covers 80%+ of cases
    2. Fall back to extruct with subprocess isolation on Linux for complex cases

    Args:
        html_content: HTML string to parse

    Returns:
        Restock: Extracted availability data

    Raises:
        MoreThanOnePriceFound: When multiple prices detected
        Other exceptions: From extruct/parsing
    """
    import platform

    # Step 1: Try pure Python extraction first (fast, no lxml, no memory leak)
    try:
        from .pure_python_extractor import extract_metadata_pure_python, query_price_availability

        logger.trace("Attempting pure Python metadata extraction (no lxml)")
        extracted_data = extract_metadata_pure_python(html_content)
        price_data = query_price_availability(extracted_data)

        # If we got price AND availability, we're done!
        if price_data.get('price') and price_data.get('availability'):
            result = Restock(price_data)
            logger.debug(f"Pure Python extraction successful: {dict(result)}")
            return result

        # If we got some data but not everything, still try extruct for completeness
        if price_data.get('price') or price_data.get('availability'):
            logger.debug(f"Pure Python extraction partial: {price_data}, will try extruct for completeness")

    except Exception as e:
        logger.debug(f"Pure Python extraction failed: {e}, falling back to extruct")

    # Step 2: Fall back to extruct (uses lxml, needs subprocess on Linux)
    logger.trace("Falling back to extruct (lxml-based) with subprocess isolation")

    # Only use subprocess isolation on Linux
    # Other platforms may have issues with spawn or don't need the aggressive memory management
    if platform.system() == 'Linux':
        import multiprocessing
        import json
        import gc

        try:
            ctx = multiprocessing.get_context('spawn')
            parent_conn, child_conn = ctx.Pipe()
            p = ctx.Process(target=_extract_itemprop_availability_worker, args=(child_conn,))
            p.start()

            # Send HTML as raw bytes (no pickle)
            html_bytes = html_content.encode('utf-8')
            parent_conn.send_bytes(html_bytes)

            # Explicitly delete html_bytes copy immediately after sending
            del html_bytes
            gc.collect()

            # Receive result as JSON
            result_bytes = parent_conn.recv_bytes()
            result = json.loads(result_bytes.decode('utf-8'))

            # Wait for subprocess to complete
            p.join()

            # Close pipes
            parent_conn.close()
            child_conn.close()

            # Clean up all subprocess-related objects
            del p, parent_conn, child_conn, result_bytes
            gc.collect()

            # Handle result or re-raise exception
            if result['success']:
                # Reconstruct Restock object from dict
                restock_obj = Restock(result['data'])
                # Clean up result dict
                del result
                gc.collect()
                return restock_obj
            else:
                # Re-raise the exception that occurred in subprocess
                exception_type = result['exception_type']
                exception_msg = result.get('exception_message', '')
                del result
                gc.collect()

                if exception_type == 'MoreThanOnePriceFound':
                    raise MoreThanOnePriceFound()
                else:
                    raise Exception(f"{exception_type}: {exception_msg}")

        except Exception as e:
            # If multiprocessing itself fails, log and fall back to direct call
            logger.warning(f"Subprocess extraction failed: {e}, falling back to direct call")
            gc.collect()
            return get_itemprop_availability(html_content)
    else:
        # Non-Linux: direct call (no subprocess overhead needed)
        return get_itemprop_availability(html_content)


# should return Restock()
# add casting?
def get_itemprop_availability(html_content) -> Restock:
    """
    Kind of funny/cool way to find price/availability in one many different possibilities.
    Use 'extruct' to find any possible RDFa/microdata/json-ld data, make a JSON string from the output then search it.
    """
    from jsonpath_ng import parse

    import re
    now = time.time()
    import extruct
    logger.trace(f"Imported extruct module in {time.time() - now:.3f}s")

    now = time.time()

    # Extruct is very slow, I'm wondering if some ML is going to be faster (800ms on my i7), 'rdfa' seems to be the heaviest.
    syntaxes = ['dublincore', 'json-ld', 'microdata', 'microformat', 'opengraph']
    try:
        data = extruct.extract(html_content, syntaxes=syntaxes)
    except Exception as e:
        logger.warning(f"Unable to extract data, document parsing with extruct failed with {type(e).__name__} - {str(e)}")
        return Restock()

    logger.trace(f"Extruct basic extract of all metadata done in {time.time() - now:.3f}s")

    # First phase, dead simple scanning of anything that looks useful
    value = Restock()
    if data:
        logger.debug("Using jsonpath to find price/availability/etc")
        price_parse = parse('$..(price|Price)')
        pricecurrency_parse = parse('$..(pricecurrency|currency|priceCurrency )')
        availability_parse = parse('$..(availability|Availability)')

        price_result = _deduplicate_prices(price_parse.find(data))
        if price_result:
            # Right now, we just support single product items, maybe we will store the whole actual metadata seperately in teh future and
            # parse that for the UI?
            if len(price_result) > 1 and len(price_result) > 1:
                # See of all prices are different, in the case that one product has many embedded data types with the same price
                # One might have $121.95 and another 121.95 etc
                logger.warning(f"More than one price found {price_result}, throwing exception, cant use this plugin.")
                raise MoreThanOnePriceFound()

            value['price'] = price_result[0]

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
            logger.debug("Alternatively digging through OpenGraph properties for restock/price info..")
            jsonpath_expr = parse('$..properties')

            for match in jsonpath_expr.find(data):
                if not value.get('price'):
                    value['price'] = _search_prop_by_value([match.value], "price:amount")
                if not value.get('availability'):
                    value['availability'] = _search_prop_by_value([match.value], "product:availability")
                if not value.get('currency'):
                    value['currency'] = _search_prop_by_value([match.value], "price:currency")
    logger.trace(f"Processed with Extruct in {time.time()-now:.3f}s")

    return value


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

    def run_changedetection(self, watch, force_reprocess=False):
        import hashlib

        if not watch:
            raise Exception("Watch no longer exists.")

        current_raw_document_checksum = self.get_raw_document_checksum()
        # Skip processing only if BOTH conditions are true:
        # 1. HTML content unchanged (checksum matches last saved checksum)
        # 2. Watch configuration was not edited (including trigger_text, filters, etc.)
        # The was_edited flag handles all watch configuration changes, so we don't need
        # separate checks for trigger_text or other processing rules.
        if (not force_reprocess and
            not watch.was_edited and
            self.last_raw_content_checksum and
            self.last_raw_content_checksum == current_raw_document_checksum):
            raise checksumFromPreviousCheckWasTheSame()

        # Unset any existing notification error
        update_obj = {'last_notification_error': False, 'last_error': False, 'restock':  Restock()}

        self.screenshot = self.fetcher.screenshot
        self.xpath_data = self.fetcher.xpath_data

        # Track the content type (readonly field, doesn't trigger was_edited)
        update_obj['content-type'] = self.fetcher.headers.get('Content-Type', '')  # Use hyphen (matches OpenAPI spec)
        update_obj["last_check_status"] = self.fetcher.get_last_status_code()

        # Save the raw content checksum to file (processor implementation detail, not watch config)
        self.update_last_raw_content_checksum(current_raw_document_checksum)

        # Only try to process restock information (like scraping for keywords) if the page was actually rendered correctly.
        # Otherwise it will assume "in stock" because nothing suggesting the opposite was found
        from ...html_tools import html_to_text
        text = html_to_text(self.fetcher.content)
        logger.debug(f"Length of text after conversion: {len(text)}")
        if not len(text):
            from ...content_fetchers.exceptions import ReplyWithContentButNoText
            raise ReplyWithContentButNoText(url=watch.link,
                                            status_code=self.fetcher.get_last_status_code(),
                                            screenshot=self.fetcher.screenshot,
                                            html_content=self.fetcher.content,
                                            xpath_data=self.fetcher.xpath_data
                                            )

        # Which restock settings to compare against?
        restock_settings = watch.get('restock_settings', {})

        # See if any tags have 'activate for individual watches in this tag/group?' enabled and use the first we find
        for tag_uuid in watch.get('tags'):
            tag = self.datastore.data['settings']['application']['tags'].get(tag_uuid, {})
            if tag.get('overrides_watch'):
                restock_settings = tag.get('restock_settings', {})
                logger.info(f"Watch {watch.get('uuid')} - Tag '{tag.get('title')}' selected for restock settings override")
                break


        itemprop_availability = {}
        multiple_prices_found = False

        # Try built-in extraction first, this will scan metadata in the HTML
        # On Linux, this runs in a subprocess to prevent lxml/extruct memory leaks
        try:
            itemprop_availability = extract_itemprop_availability_safe(self.fetcher.content)
        except MoreThanOnePriceFound as e:
            # Don't raise immediately - let plugins try to handle this case
            # Plugins might be able to determine which price is correct
            logger.warning(f"Built-in detection found multiple prices on {watch.get('url')}, will try plugin override")
            multiple_prices_found = True
            itemprop_availability = {}

        # If built-in extraction didn't get both price AND availability, try plugin override
        # Only check plugin if this watch is using a fetcher that might provide better data
        has_price = itemprop_availability.get('price') is not None
        has_availability = itemprop_availability.get('availability') is not None

        # @TODO !!! some setting like "Use as fallback" or "always use", "t
        if not (has_price and has_availability) or True:
            from changedetectionio.pluggy_interface import get_itemprop_availability_from_plugin
            fetcher_name = watch.get('fetch_backend', 'html_requests')

            # Resolve 'system' to the actual fetcher being used
            # This allows plugins to work even when watch uses "system settings default"
            if fetcher_name == 'system':
                # Get the actual fetcher that was used (from self.fetcher)
                # Fetcher class name gives us the actual backend (e.g., 'html_requests', 'html_webdriver')
                actual_fetcher = type(self.fetcher).__name__
                if 'html_requests' in actual_fetcher.lower():
                    fetcher_name = 'html_requests'
                elif 'webdriver' in actual_fetcher.lower() or 'playwright' in actual_fetcher.lower():
                    fetcher_name = 'html_webdriver'
                logger.debug(f"Resolved 'system' fetcher to actual fetcher: {fetcher_name}")

            # Try plugin override - plugins can decide if they support this fetcher
            if fetcher_name:
                logger.debug(f"Calling extra plugins for getting item price/availability (fetcher: {fetcher_name})")
                plugin_availability = get_itemprop_availability_from_plugin(self.fetcher.content, fetcher_name, self.fetcher, watch.link)

                if plugin_availability:
                    # Plugin provided better data, use it
                    plugin_has_price = plugin_availability.get('price') is not None
                    plugin_has_availability = plugin_availability.get('availability') is not None

                    # Only use plugin data if it's actually better than what we have
                    if plugin_has_price or plugin_has_availability:
                        itemprop_availability = plugin_availability
                        logger.info(f"Using plugin-provided availability data for fetcher '{fetcher_name}' (built-in had price={has_price}, availability={has_availability}; plugin has price={plugin_has_price}, availability={plugin_has_availability})")
                if not plugin_availability:
                    logger.debug("No item price/availability from plugins")

        # If we had multiple prices and plugins also failed, NOW raise the exception
        if multiple_prices_found and not itemprop_availability.get('price'):
            raise ProcessorException(
                message="Cannot run, more than one price detected, this plugin is only for product pages with ONE product, try the content-change detection mode.",
                url=watch.get('url'),
                status_code=self.fetcher.get_last_status_code(),
                screenshot=self.fetcher.screenshot,
                xpath_data=self.fetcher.xpath_data
            )

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

        # Main detection method
        fetched_md5 = None

        # store original price if not set
        if itemprop_availability and itemprop_availability.get('price') and not itemprop_availability.get('original_price'):
            itemprop_availability['original_price'] = itemprop_availability.get('price')
            update_obj['restock']["original_price"] = itemprop_availability.get('price')

        if not self.fetcher.instock_data and not itemprop_availability.get('availability') and not itemprop_availability.get('price'):
            raise ProcessorException(
                message=f"Unable to extract restock data for this page unfortunately. (Got code {self.fetcher.get_last_status_code()} from server), no embedded stock information was found and nothing interesting in the text, try using this watch with Chrome.",
                url=watch.get('url'),
                status_code=self.fetcher.get_last_status_code(),
                screenshot=self.fetcher.screenshot,
                xpath_data=self.fetcher.xpath_data
                )

        logger.debug(f"self.fetcher.instock_data is - '{self.fetcher.instock_data}' and itemprop_availability.get('availability') is {itemprop_availability.get('availability')}")
        # Nothing automatic in microdata found, revert to scraping the page
        if self.fetcher.instock_data and itemprop_availability.get('availability') is None:
            # 'Possibly in stock' comes from stock-not-in-stock.js when no string found above the fold.
            # Careful! this does not really come from chrome/js when the watch is set to plaintext
            update_obj['restock']["in_stock"] = True if self.fetcher.instock_data == 'Possibly in stock' else False
            logger.debug(f"Watch UUID {watch.get('uuid')} restock check returned instock_data - '{self.fetcher.instock_data}' from JS scraper.")

        # Very often websites will lie about the 'availability' in the metadata, so if the scraped version says its NOT in stock, use that.
        if self.fetcher.instock_data and self.fetcher.instock_data != 'Possibly in stock':
            if update_obj['restock'].get('in_stock'):
                logger.warning(
                    f"Lie detected in the availability machine data!! when scraping said its not in stock!! itemprop was '{itemprop_availability}' and scraped from browser was '{self.fetcher.instock_data}' update obj was {update_obj['restock']} ")
                logger.warning(f"Setting instock to FALSE, scraper found '{self.fetcher.instock_data}' in the body but metadata reported not-in-stock")
                update_obj['restock']["in_stock"] = False

        # What we store in the snapshot
        price = update_obj.get('restock').get('price') if update_obj.get('restock').get('price') else ""
        snapshot_content = f"In Stock: {update_obj.get('restock').get('in_stock')} - Price: {price}"

        # Main detection method
        fetched_md5 = hashlib.md5(snapshot_content.encode('utf-8')).hexdigest()

        # The main thing that all this at the moment comes down to :)
        changed_detected = False
        logger.debug(f"Watch UUID {watch.get('uuid')} restock check - Previous MD5: {watch.get('previous_md5')}, Fetched MD5 {fetched_md5}")

        # out of stock -> back in stock only?
        if watch.get('restock') and watch['restock'].get('in_stock') != update_obj['restock'].get('in_stock'):
            # Yes if we only care about it going to instock, AND we are in stock
            if restock_settings.get('in_stock_processing') == 'in_stock_only' and update_obj['restock']['in_stock']:
                changed_detected = True

            if restock_settings.get('in_stock_processing') == 'all_changes':
                # All cases
                changed_detected = True

        if restock_settings.get('follow_price_changes') and watch.get('restock') and update_obj.get('restock') and update_obj['restock'].get('price'):
            price = float(update_obj['restock'].get('price'))
            # Default to current price if no previous price found
            if watch['restock'].get('original_price'):
                previous_price = float(watch['restock'].get('original_price'))
                # It was different, but negate it further down
                if price != previous_price:
                    changed_detected = True

            # Minimum/maximum price limit
            if update_obj.get('restock') and update_obj['restock'].get('price'):
                logger.debug(
                    f"{watch.get('uuid')} - Change was detected, 'price_change_max' is '{restock_settings.get('price_change_max', '')}' 'price_change_min' is '{restock_settings.get('price_change_min', '')}', price from website is '{update_obj['restock'].get('price', '')}'.")
                if update_obj['restock'].get('price'):
                    min_limit = float(restock_settings.get('price_change_min')) if restock_settings.get('price_change_min') else None
                    max_limit = float(restock_settings.get('price_change_max')) if restock_settings.get('price_change_max') else None

                    price = float(update_obj['restock'].get('price'))
                    logger.debug(f"{watch.get('uuid')} after float conversion - Min limit: '{min_limit}' Max limit: '{max_limit}' Price: '{price}'")
                    if min_limit or max_limit:
                        if is_between(number=price, lower=min_limit, upper=max_limit):
                            # Price was between min/max limit, so there was nothing todo in any case
                            logger.trace(f"{watch.get('uuid')} {price} is between {min_limit} and {max_limit}, nothing to check, forcing changed_detected = False (was {changed_detected})")
                            changed_detected = False
                        else:
                            logger.trace(f"{watch.get('uuid')} {price} is between {min_limit} and {max_limit}, continuing normal comparison")

                    # Price comparison by %
                    if watch['restock'].get('original_price') and changed_detected and restock_settings.get('price_change_threshold_percent'):
                        previous_price = float(watch['restock'].get('original_price'))
                        pc = float(restock_settings.get('price_change_threshold_percent'))
                        change = abs((price - previous_price) / previous_price * 100)
                        if change and change <= pc:
                            logger.debug(f"{watch.get('uuid')} Override change-detected to FALSE because % threshold ({pc}%) was {change:.3f}%")
                            changed_detected = False
                        else:
                            logger.debug(f"{watch.get('uuid')} Price change was {change:.3f}% , (threshold {pc}%)")

        # Always record the new checksum
        update_obj["previous_md5"] = fetched_md5

        return changed_detected, update_obj, snapshot_content.strip()
