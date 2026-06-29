"""
Pure Python metadata extractor - no lxml, no memory leaks.

This module provides a fast, memory-efficient alternative to extruct for common
e-commerce metadata extraction. It handles:
- JSON-LD (covers 80%+ of modern sites)
- OpenGraph meta tags
- Basic microdata attributes

Uses Python's built-in html.parser instead of lxml/libxml2, avoiding C-level
memory allocation issues. For edge cases, the main processor can fall back to
extruct (with subprocess isolation on Linux).
"""

from html.parser import HTMLParser
import json
import re
from loguru import logger


class JSONLDExtractor(HTMLParser):
    """
    Extract JSON-LD structured data from HTML.

    Finds all <script type="application/ld+json"> tags and parses their content.
    Handles multiple JSON-LD blocks on the same page.
    """

    def __init__(self):
        super().__init__()
        self.in_jsonld = False
        self.data = []  # List of all parsed JSON-LD objects
        self.current_script = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            # Check if this is a JSON-LD script tag
            for attr, value in attrs:
                if attr == 'type' and value == 'application/ld+json':
                    self.in_jsonld = True
                    self.current_script = []
                    break

    def handle_data(self, data):
        if self.in_jsonld:
            self.current_script.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.in_jsonld:
            # Parse the accumulated script content
            script_content = ''.join(self.current_script)
            if script_content.strip():
                try:
                    # Parse JSON (handles both objects and arrays)
                    parsed = json.loads(script_content)
                    if isinstance(parsed, list):
                        self.data.extend(parsed)
                    else:
                        self.data.append(parsed)
                except json.JSONDecodeError as e:
                    logger.debug(f"Failed to parse JSON-LD: {e}")
                    pass

            self.in_jsonld = False
            self.current_script = []


class OpenGraphExtractor(HTMLParser):
    """
    Extract OpenGraph meta tags from HTML.

    Finds <meta property="og:*"> tags commonly used for social media sharing.
    """

    def __init__(self):
        super().__init__()
        self.og_data = {}

    def handle_starttag(self, tag, attrs):
        if tag == 'meta':
            attrs_dict = dict(attrs)
            prop = attrs_dict.get('property', '')

            # Extract OpenGraph properties
            if prop.startswith('og:'):
                content = attrs_dict.get('content', '')
                if content:
                    self.og_data[prop] = content


class MicrodataExtractor(HTMLParser):
    """
    Extract basic microdata attributes from HTML.

    Finds elements with itemprop attributes. This is a simplified extractor
    that doesn't handle nested itemscope/itemtype hierarchies - for complex
    cases, use extruct as fallback.
    """

    def __init__(self):
        super().__init__()
        self.microdata = {}
        self.current_itemprop = None

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        if 'itemprop' in attrs_dict:
            itemprop = attrs_dict['itemprop']

            # Price/currency/availability can be in content/href attributes
            if itemprop == 'price':
                if 'content' in attrs_dict:
                    self.microdata['price'] = attrs_dict['content']
                else:
                    self.current_itemprop = 'price'

            elif itemprop == 'priceCurrency':
                if 'content' in attrs_dict:
                    self.microdata['currency'] = attrs_dict['content']
                else:
                    self.current_itemprop = 'priceCurrency'

            elif itemprop == 'availability':
                # Can be in href (link) or content (meta)
                if 'href' in attrs_dict:
                    self.microdata['availability'] = attrs_dict['href']
                elif 'content' in attrs_dict:
                    self.microdata['availability'] = attrs_dict['content']
                else:
                    self.current_itemprop = 'availability'

    def handle_data(self, data):
        # Capture text content for itemprop elements
        if self.current_itemprop == 'price':
            # Try to extract numeric price from text
            try:
                price_text = re.sub(r'[^\d.]', '', data.strip())
                if price_text:
                    self.microdata['price'] = float(price_text)
            except ValueError:
                pass
        elif self.current_itemprop == 'priceCurrency':
            currency = data.strip()
            if currency:
                self.microdata['currency'] = currency
        elif self.current_itemprop == 'availability':
            availability = data.strip()
            if availability:
                self.microdata['availability'] = availability

    def handle_endtag(self, tag):
        # Reset current itemprop after closing tag
        self.current_itemprop = None


def extract_metadata_pure_python(html_content):
    """
    Extract structured metadata from HTML using pure Python parsers.

    Returns a dict with three keys:
    - 'json-ld': List of parsed JSON-LD objects
    - 'opengraph': Dict of OpenGraph properties
    - 'microdata': Dict of microdata properties

    Args:
        html_content: HTML string to parse

    Returns:
        dict: Extracted metadata in three formats
    """
    result = {
        'json-ld': [],
        'opengraph': {},
        'microdata': {}
    }

    # Extract JSON-LD
    try:
        jsonld_extractor = JSONLDExtractor()
        jsonld_extractor.feed(html_content)
        result['json-ld'] = jsonld_extractor.data
        logger.trace(f"Pure Python: Found {len(jsonld_extractor.data)} JSON-LD blocks")
    except Exception as e:
        logger.debug(f"JSON-LD extraction failed: {e}")

    # Extract OpenGraph
    try:
        og_extractor = OpenGraphExtractor()
        og_extractor.feed(html_content)
        result['opengraph'] = og_extractor.og_data
        if result['opengraph']:
            logger.trace(f"Pure Python: Found {len(og_extractor.og_data)} OpenGraph tags")
    except Exception as e:
        logger.debug(f"OpenGraph extraction failed: {e}")

    # Extract Microdata
    try:
        microdata_extractor = MicrodataExtractor()
        microdata_extractor.feed(html_content)
        result['microdata'] = microdata_extractor.microdata
        if result['microdata']:
            logger.trace(f"Pure Python: Found microdata: {result['microdata']}")
    except Exception as e:
        logger.debug(f"Microdata extraction failed: {e}")

    return result


def query_price_availability(extracted_data):
    """
    Query extracted metadata for price and availability information.

    Uses jsonpath_ng to query JSON-LD data (same approach as extruct).
    Falls back to OpenGraph and microdata if JSON-LD doesn't have the data.

    Args:
        extracted_data: Dict from extract_metadata_pure_python()

    Returns:
        dict: {'price': float, 'currency': str, 'availability': str}
    """
    from jsonpath_ng import parse

    result = {}

    # 1. Try JSON-LD first (most reliable and common)
    for data in extracted_data.get('json-ld', []):
        try:
            # Use jsonpath to find price/availability anywhere in the structure
            price_parse = parse('$..(price|Price)')
            availability_parse = parse('$..(availability|Availability)')
            currency_parse = parse('$..(priceCurrency|currency|priceCurrency)')

            price_results = [m.value for m in price_parse.find(data)]
            if price_results and not result.get('price'):
                # Handle various price formats
                price_val = price_results[0]
                if isinstance(price_val, (int, float)):
                    result['price'] = float(price_val)
                elif isinstance(price_val, str):
                    # Extract numeric value from string
                    try:
                        result['price'] = float(re.sub(r'[^\d.]', '', price_val))
                    except ValueError:
                        pass

            avail_results = [m.value for m in availability_parse.find(data)]
            if avail_results and not result.get('availability'):
                result['availability'] = str(avail_results[0])

            curr_results = [m.value for m in currency_parse.find(data)]
            if curr_results and not result.get('currency'):
                result['currency'] = str(curr_results[0])

            # If we found price, this JSON-LD block is good
            if result.get('price'):
                logger.debug(f"Pure Python: Found price data in JSON-LD: {result}")
                break

        except Exception as e:
            logger.debug(f"Error querying JSON-LD: {e}")
            continue

    # 2. Try OpenGraph if JSON-LD didn't provide everything
    og_data = extracted_data.get('opengraph', {})
    if not result.get('price') and 'og:price:amount' in og_data:
        try:
            result['price'] = float(og_data['og:price:amount'])
        except ValueError:
            pass
    if not result.get('currency') and 'og:price:currency' in og_data:
        result['currency'] = og_data['og:price:currency']
    if not result.get('availability') and 'og:availability' in og_data:
        result['availability'] = og_data['og:availability']

    # 3. Use microdata as last resort
    microdata = extracted_data.get('microdata', {})
    if not result.get('price') and 'price' in microdata:
        result['price'] = microdata['price']
    if not result.get('currency') and 'currency' in microdata:
        result['currency'] = microdata['currency']
    if not result.get('availability') and 'availability' in microdata:
        result['availability'] = microdata['availability']

    # result['price'] could be float or str here, depending on the website, for example it might contain "1,00" commas, etc.
    # using something like babel you need to know the locale of the website and even then it can be problematic
    # we dont really do anything with the price data so far.. so just accept it the way it comes.
    return result


# =============================================================================
# Structured metadata for the LLM enricher — passed through verbatim
# =============================================================================
#
# This surfaces the page's structured metadata (JSON-LD + OpenGraph site/type)
# as-is for the LLM intent/summary prompts. We deliberately do NOT curate, field-
# cherry-pick, or impose a size limit here:
#
#   * LLMs are trained on schema.org JSON-LD and read it natively, so handing it
#     over verbatim lets ANY user intent ("list the SKUs", "did the release date
#     change?", "is it a recipe or a product?") work without us pre-guessing which
#     fields matter — and it covers non-product pages (NewsArticle, Event, JobPosting…)
#     for free.
#   * There is exactly one configurable budget for how much text reaches the LLM —
#     max_input_chars (env LLM_MAX_INPUT_CHARS → settings → default), enforced by the
#     evaluator. A second hardcoded cap here would be a competing, non-configurable
#     source of truth. The caller decides how much fits.
#
# Extraction reuses the memory-safe extract_metadata_pure_python() (stdlib
# html.parser, no lxml/libxml2) so it is safe to call on every changed watch
# without the C-level leak extruct/lxml carries, and it is robust to dangling/
# unclosed <script type="application/ld+json"> blocks (HTMLParser only emits a
# block on a real closing tag, so an unterminated blob is dropped rather than
# swallowing the rest of the document the way a greedy regex would).
# =============================================================================


def extract_metadata_for_llm(html_content) -> str:
    """
    Return the page's structured metadata verbatim for LLM context, or '' if none.

    Output (either part omitted when absent):

        Page context: site: ExampleShop | og:type: product
        Structured metadata found on the page (JSON-LD):
        {"@type":"Product","name":"Acme Widget","sku":"12345", ...}
        {"@type":"BreadcrumbList", ...}

    JSON-LD blocks are re-serialised compactly (this only strips source whitespace
    — the data is byte-for-byte the same schema.org structure). No truncation or
    field selection is applied; sizing is the caller's single configurable budget.
    """
    if not html_content:
        return ''

    try:
        data = extract_metadata_pure_python(html_content)
    except Exception as e:
        logger.debug(f"Metadata for LLM: extraction failed: {e}")
        return ''

    parts = []

    # OpenGraph site/type — page-kind context that is NOT carried in JSON-LD,
    # so the model can tell an e-shop listing from a news feed.
    og = data.get('opengraph', {})
    ctx = []
    if og.get('og:site_name'):
        ctx.append(f"site: {og['og:site_name']}")
    if og.get('og:type'):
        ctx.append(f"og:type: {og['og:type']}")
    if ctx:
        parts.append('Page context: ' + ' | '.join(ctx))

    # JSON-LD verbatim (compact re-dump only — whitespace normalisation, not curation).
    nodes = data.get('json-ld', [])
    if nodes:
        try:
            blob = '\n'.join(
                json.dumps(n, ensure_ascii=False, separators=(',', ':'))
                for n in nodes
            )
        except (TypeError, ValueError) as e:
            logger.debug(f"Metadata for LLM: JSON-LD re-serialise failed: {e}")
            blob = ''
        if blob:
            parts.append('Structured metadata found on the page (JSON-LD):\n' + blob)

    return '\n'.join(parts)
