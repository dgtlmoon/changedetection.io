"""
LLM context enrichment plugin — structured product/page metadata.

Surfaces the page's structured metadata (JSON-LD + OpenGraph site/type) verbatim
so it can be appended to the LLM intent/summary prompts. This lets user intents
and summary prompts reference facts the html-to-text snapshot has stripped out —
prices, SKUs/GTINs, availability, ratings, article dates, page kind, etc.

Extraction reuses the memory-safe pure_python_extractor (stdlib html.parser, no
lxml/libxml2), so it is safe to run on every changed watch without the C-level
memory leak that extruct/lxml carries. It performs NO LLM call of its own and
imposes no size limit — the evaluator enforces the single configurable
max_input_chars budget and drops the enrichment if it would not fit.
"""
from loguru import logger
from changedetectionio.pluggy_interface import hookimpl


@hookimpl
def llm_context_enrich(watch, html_content, datastore):
    """Return verbatim structured metadata for the current page, or None."""
    if not html_content:
        return None

    try:
        from changedetectionio.processors.restock_diff.pure_python_extractor import extract_metadata_for_llm
        block = extract_metadata_for_llm(html_content)
    except Exception as e:
        logger.debug(f"llm_metadata_enrich: extraction failed: {e}")
        return None

    return block or None
