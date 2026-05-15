"""
LLM fallback plugin for price and restock info extraction.

When the built-in structured-metadata extraction (JSON-LD, microdata, OpenGraph)
fails to produce both a price and availability, this plugin is called as a last
resort.  It sends a trimmed, HTML-stripped version of the page to the configured
LLM and asks it to return a structured JSON answer.

The module-level `datastore` variable is injected at startup by
`inject_datastore_into_plugins()` in pluggy_interface.py.
"""
import json
import re
from loguru import logger
from changedetectionio.pluggy_interface import hookimpl
from changedetectionio.llm.evaluator import apply_local_token_multiplier

# Injected at startup by inject_datastore_into_plugins()
datastore = None

SYSTEM_PROMPT = (
    'You are an expert price and restock extraction utility. '
    'Your task is to analyse a product page and determine the price and stock status of the MAIN product only.\n\n'

    'AVAILABILITY — treat as "in stock":\n'
    '- Action buttons near the product: "Add to cart", "Add to basket", "Buy now", '
    '"Order now", "Purchase", "Import", "Add to bag", "Add to trolley", "In stock", '
    '"Available", "Ships in X days/weeks", "In store", "Pick up today".\n'
    '- "Pre-order" or "Reserve" — the item is orderable, treat as "in stock".\n'
    '- "Only X left", "Almost gone", "Low stock", "Limited availability" — still in stock.\n'
    '- "Request a quote" or "Contact us for pricing" — item is available, price is null.\n'
    '- IMPORTANT: Ignore cart/basket/bag links in the page HEADER or navigation bar '
    '(e.g. a shopping cart icon showing item count). That reflects what is already in '
    'the visitor\'s cart — it says nothing about whether THIS product is available.\n\n'

    'PRICE — what NOT to use:\n'
    '- A "$0.00" or "0" that appears near header/nav links such as "Login", "Wishlist", '
    '"Contact Us", "My Account" is an empty shopping-cart indicator, NOT the product price. '
    'Ignore it entirely — return null for price rather than 0 in this situation.\n'
    '- Only return 0 (free) when the page clearly states the product itself costs nothing '
    '(e.g. "Free", "Free download", "Price: $0").\n\n'

    'AVAILABILITY — treat as "out of stock":\n'
    '- "Out of stock", "Sold out", "Unavailable", "Currently unavailable", '
    '"Temporarily out of stock", "Discontinued", "No longer available", '
    '"Notify me when available", "Email me when back", "Join waitlist".\n\n'

    'AVAILABILITY — return null when uncertain:\n'
    '- The page asks the user to select a size, colour, or other variant first '
    '("Select an option", "Choose a size") — availability depends on the variant, so return null.\n'
    '- You cannot clearly tell from the page content whether the item is available.\n\n'

    'PRICE rules:\n'
    '- Extract the main selling price as a plain number, no currency symbol.\n'
    '- Prices may use any popular locale format — interpret them all correctly and return a plain decimal number. '
    'Examples: "10 000 Kč" = 10000, "1.299,95 €" = 1299.95, "1,299.95" = 1299.95, '
    '"10 000,50" = 10000.50, "£1.299" = 1299, "¥10000" = 10000.\n'
    '- If both an original (crossed-out) price and a sale/current price appear, use the sale price.\n'
    '- "From $X" or "Starting at $X" are teaser prices — prefer a definite price or return null.\n'
    '- A price of 0 (free) is valid — return 0, not null.\n'
    '- If pricing requires a quote or login, return null for price.\n'
    '- Ignore prices shown in search/filter UI elements (e.g. "Price from: — to:").\n'
    '- IMPORTANT: Ignore ALL prices that appear inside or below recommendation/discovery blocks '
    'such as: "Similar items", "You may also like", "Customers also bought", '
    '"Based on your browsing", "Based on your shopping", "Frequently bought together", '
    '"People also viewed", "Related products", "Sponsored products", "More like this", '
    '"Other sellers", "Compare with similar items". '
    'These sections contain prices for OTHER products, not the main product.\n'
    '- When multiple prices appear on the page, prefer the price that is positioned '
    'earliest/highest in the page content — it is almost always the main product price. '
    'Prices appearing after large blocks of descriptive text or review sections are '
    'likely from recommendation widgets and should be ignored.\n\n'

    'CLASSIFIEDS AND LISTING PAGES:\n'
    '- On classifieds or marketplace sites (e.g. eBay listings, Craigslist, Bazoš, Gumtree), '
    'if a price is shown alongside seller contact details or a "Contact seller" link, '
    'treat the item as "instock" — the listing being active means it is available.\n\n'

    'Return ONLY a JSON object with exactly these three keys:\n'
    '  "price"        — number or null\n'
    '  "currency"     — ISO-4217 code (USD, EUR, GBP …) or null\n'
    '  "availability" — exactly one of: "instock", "outofstock", or null\n'
    '                   Use "instock" when the product can be ordered/purchased.\n'
    '                   Use "outofstock" when it cannot.\n'
    '                   Use null when you genuinely cannot tell.\n'
    'No markdown, no backticks, no explanation — pure JSON only.'
)

_MAX_CONTENT_CHARS = 8_000


def _extract_jsonld(html_content: str) -> str:
    """Extract JSON-LD blocks — these contain reliable structured product data."""
    blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html_content, flags=re.DOTALL | re.IGNORECASE
    )
    if not blocks:
        return ''
    combined = ' '.join(b.strip() for b in blocks)
    return combined[:2000]


# Semantic tags always treated as chrome (nav/header/footer)
_CHROME_TAGS = {'nav', 'header', 'footer', 'aside'}

# id/class fragments that strongly indicate navigation or site-chrome
_CHROME_PATTERNS = re.compile(
    r'\b(nav|navigation|navbar|menu|mega-menu|breadcrumb|breadcrumbs?|'
    r'site-header|page-header|top-bar|top-nav|top-header|mobile-nav|header-bar|'
    r'site-footer|page-footer|footer-links|related|similar|'
    r'you-?may-?also|customers?-?also|frequently-?bought|'
    r'people-?also|sponsored|recommendation|widget|sidebar|'
    r'cross-?sell|up-?sell)\b',
    re.IGNORECASE,
)


def _remove_chrome(html_content: str) -> str:
    """Use BS4 to strip navigation, header, footer and recommendation noise.

    Uses html.parser (built-in, no lxml) to avoid memory leak issues.
    Falls back to the original HTML string if BS4 fails for any reason.
    """
    try:
        from bs4 import BeautifulSoup, Tag
        soup = BeautifulSoup(html_content, 'html.parser')

        # Snapshot the full tag list before any decompositions so we don't
        # mutate the tree while iterating it.  After a parent is decomposed
        # its children become orphans (parent=None) — skip those.
        for tag in list(soup.find_all(True)):
            if not isinstance(tag, Tag) or tag.parent is None:
                continue
            name = tag.name or ''
            if name in _CHROME_TAGS:
                tag.decompose()
                continue
            try:
                cls_list = tag.get('class') or []
                cls_str = ' '.join(cls_list) if isinstance(cls_list, list) else str(cls_list)
                id_str = tag.get('id') or ''
            except Exception:
                continue
            if _CHROME_PATTERNS.search(cls_str + ' ' + id_str):
                tag.decompose()

        return str(soup)
    except Exception as e:
        logger.debug(f"BS4 chrome removal failed ({e}), using raw HTML")
        return html_content


def _strip_html(html_content: str) -> str:
    """HTML-to-text for LLM consumption.

    1. Extracts JSON-LD (structured product data) to prepend.
    2. Strips nav/header/footer/recommendation blocks via BS4.
    3. Removes all remaining tags and collapses whitespace.
    JSON-LD is prepended so reliable price/availability data is always visible
    to the LLM regardless of how deep it sits in the page.
    """
    jsonld = _extract_jsonld(html_content)

    # Remove site-chrome before generic tag stripping
    cleaned = _remove_chrome(html_content)

    # Drop HTML comments (can contain large disabled markup blocks)
    text = re.sub(r'<!--.*?-->', ' ', cleaned, flags=re.DOTALL)
    # Drop all <script> and <style> blocks
    text = re.sub(r'<(script|style)[^>]*>.*?</(script|style)>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Decode common entities
    text = (text
            .replace('&nbsp;', ' ')
            .replace('&amp;', '&')
            .replace('&lt;', '<')
            .replace('&gt;', '>')
            .replace('&quot;', '"')
            .replace('&#39;', "'"))
    text = re.sub(r'\s+', ' ', text).strip()

    if jsonld:
        budget = _MAX_CONTENT_CHARS - len(jsonld) - 1
        return (jsonld + ' ' + text[:budget]).strip()
    return text[:_MAX_CONTENT_CHARS]


@hookimpl
def get_itemprop_availability_override(content, fetcher_name, fetcher_instance, url, llm_intent=None):
    """Use an LLM as a last-resort fallback for price and restock extraction."""
    global datastore

    if datastore is None:
        logger.debug("LLM restock fallback: no datastore injected yet, skipping")
        return None

    # Gate on the user setting (default True — enabled out of the box)
    app_settings = datastore.data.get('settings', {}).get('application', {})
    if not app_settings.get('llm_restock_use_fallback_extract', True):
        logger.debug("LLM restock fallback: disabled in settings")
        return None

    try:
        from changedetectionio.llm.evaluator import get_llm_config, accumulate_global_tokens
        from changedetectionio.llm import client as llm_client
    except ImportError as e:
        logger.debug(f"LLM restock fallback: LLM libraries not available ({e})")
        return None

    llm_cfg = get_llm_config(datastore)
    if not llm_cfg or not llm_cfg.get('model'):
        logger.debug("LLM restock fallback: no LLM model configured, skipping")
        return None

    text_content = _strip_html(content) if content else ''
    logger.debug(f"LLM restock fallback: stripped HTML to {len(text_content)} chars for {url}")
    if not text_content.strip():
        logger.debug("LLM restock fallback: no text content after stripping HTML")
        return None

    logger.info(f"LLM restock fallback: using LLM ({llm_cfg['model']}) for price/stock extraction - {url}")

    user_prompt = f'URL: {url or "unknown"}\n\nPage content:\n{text_content}'
    if llm_intent:
        user_prompt += f'\n\nUser notification intent: {llm_intent}'

    try:
        raw, tokens, input_tokens, output_tokens = llm_client.completion(
            model=llm_cfg['model'],
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': user_prompt},
            ],
            api_key=llm_cfg.get('api_key'),
            api_base=llm_cfg.get('api_base'),
            # 80 fits a {price, currency, availability} JSON answer comfortably for cloud
            # models. Local reasoning models burn most of that on chain-of-thought before
            # the JSON lands — the multiplier scales it up only when provider_kind says so.
            max_tokens=apply_local_token_multiplier(80, llm_cfg),
        )

        accumulate_global_tokens(
            datastore, tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=llm_cfg['model'],
        )

        # Strip optional markdown fences the model might add
        raw = raw.strip()
        if raw.startswith('```'):
            raw = re.sub(r'^```[a-z]*\n?', '', raw)
            raw = raw.rstrip('`').strip()

        logger.debug(f"LLM restock fallback raw response: {raw!r}")

        result = json.loads(raw)

        price = result.get('price')
        currency = result.get('currency') or None
        availability = result.get('availability') or None

        # Normalise price to float
        if price is not None:
            try:
                if isinstance(price, str):
                    price = float(re.sub(r'[^\d.]', '', price))
                else:
                    price = float(price)
            except (ValueError, TypeError):
                logger.warning(f"LLM restock fallback: could not convert price {price!r} to float, ignoring")
                price = None

        if price is None and not availability:
            logger.info(f"LLM restock fallback: LLM returned no usable price or availability for {url} (raw: {raw!r})")
            return None

        logger.info(
            f"LLM restock fallback result: price={price} currency={currency} "
            f"availability={availability!r} url={url}"
        )
        return {
            'price': price,
            'currency': currency,
            'availability': availability,
            '_tokens': tokens,
            '_input_tokens': input_tokens,
            '_output_tokens': output_tokens,
            '_model': llm_cfg['model'],
        }

    except json.JSONDecodeError as e:
        logger.warning(f"LLM restock fallback: JSON parse failed ({e}) - raw response was: {raw!r}")
        return None
    except Exception as e:
        logger.warning(f"LLM restock fallback: extraction failed for {url}: {e}")
        return None
