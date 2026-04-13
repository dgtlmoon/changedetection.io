"""
Curated "watch recipes" — one-click starting points for common monitoring tasks.

Each recipe is a dict with:
    id            : stable slug (used in the URL/form).
    name          : human-readable title.
    description   : one-sentence explanation shown in the browse UI.
    category      : grouping tag (shopping, dev, news, research, social, …).
    domain_hints  : list of hostnames; used by client-side autodetect when the
                    user pastes a URL on the add-watch form.
    url_example   : sample URL the user can click-fill for quick testing.
    extras        : dict passed verbatim to ChangeDetectionStore.add_watch(extras=…).
                    Fields match the whitelist in store.add_watch (include_filters,
                    subtractive_selectors, trigger_text, ignore_text, processor,
                    title, tag, use_page_title_in_list, fetch_backend …).

Keep this list conservative — every recipe should work out-of-the-box with the
default fetcher when possible. Anything browser-dependent is flagged with
fetch_backend='html_webdriver' so users see that they need a browser fetcher.
"""

RECIPES = [
    {
        "id": "amazon-product",
        "name": "Amazon product page",
        "description": "Track price and availability on an Amazon product listing.",
        "category": "shopping",
        "domain_hints": ["amazon.com", "amazon.co.uk", "amazon.de", "amazon.in",
                         "amazon.ca", "amazon.com.au", "amazon.co.jp",
                         "amazon.fr", "amazon.it", "amazon.es"],
        "url_example": "https://www.amazon.com/dp/B0EXAMPLE",
        "extras": {
            "processor": "restock_diff",
            "use_page_title_in_list": True,
        },
    },
    {
        "id": "ebay-listing",
        "name": "eBay listing",
        "description": "Monitor price and stock state of an eBay item.",
        "category": "shopping",
        "domain_hints": ["ebay.com", "ebay.co.uk", "ebay.de", "ebay.com.au"],
        "url_example": "https://www.ebay.com/itm/123456789",
        "extras": {
            "processor": "restock_diff",
            "use_page_title_in_list": True,
        },
    },
    {
        "id": "producthunt-new",
        "name": "Product Hunt — new launches",
        "description": "Notify when Product Hunt surfaces new top launches.",
        "category": "shopping",
        "domain_hints": ["producthunt.com"],
        "url_example": "https://www.producthunt.com/",
        "extras": {
            "include_filters": ["[data-test^='post-item']"],
            "use_page_title_in_list": True,
        },
    },

    # --- Developer / release monitoring ---
    {
        "id": "github-releases",
        "name": "GitHub releases",
        "description": "Alert on new releases of a GitHub repository (via the Atom feed).",
        "category": "dev",
        "domain_hints": ["github.com"],
        "url_example": "https://github.com/owner/repo/releases.atom",
        "extras": {
            "title": "GitHub releases",
            "use_page_title_in_list": True,
        },
    },
    {
        "id": "pypi-releases",
        "name": "PyPI package releases",
        "description": "New releases of a Python package on PyPI.",
        "category": "dev",
        "domain_hints": ["pypi.org"],
        "url_example": "https://pypi.org/rss/project/requests/releases.xml",
        "extras": {
            "title": "PyPI releases",
            "use_page_title_in_list": True,
        },
    },
    {
        "id": "npm-releases",
        "name": "npm package releases",
        "description": "New published versions of an npm package.",
        "category": "dev",
        "domain_hints": ["npmjs.com", "registry.npmjs.org"],
        "url_example": "https://registry.npmjs.org/express",
        "extras": {
            "include_filters": ["$.time"],
            "title": "npm releases",
        },
    },
    {
        "id": "cve-feed",
        "name": "NVD CVE feed",
        "description": "Track new CVEs matching a keyword via the NVD JSON feed.",
        "category": "dev",
        "domain_hints": ["nvd.nist.gov"],
        "url_example": "https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=openssl",
        "extras": {
            "include_filters": ["$.vulnerabilities[*].cve.id"],
            "title": "CVE watch",
        },
    },

    # --- News / content ---
    {
        "id": "hackernews-front",
        "name": "Hacker News — front page",
        "description": "Top stories on the Hacker News front page.",
        "category": "news",
        "domain_hints": ["news.ycombinator.com"],
        "url_example": "https://news.ycombinator.com/",
        "extras": {
            "include_filters": [".athing .titleline a"],
            "title": "Hacker News front page",
        },
    },
    {
        "id": "reddit-subreddit",
        "name": "Reddit subreddit — new posts",
        "description": "New posts in a subreddit (via the .rss feed — no login needed).",
        "category": "social",
        "domain_hints": ["reddit.com", "old.reddit.com"],
        "url_example": "https://www.reddit.com/r/programming/new/.rss",
        "extras": {
            "title": "Reddit /r/… new",
            "use_page_title_in_list": True,
        },
    },
    {
        "id": "youtube-channel",
        "name": "YouTube channel uploads",
        "description": "New videos from a YouTube channel (via the official Atom feed).",
        "category": "social",
        "domain_hints": ["youtube.com"],
        "url_example": "https://www.youtube.com/feeds/videos.xml?channel_id=UCxxxxxxxxxxxxxxxxxx",
        "extras": {
            "title": "YouTube channel",
        },
    },
    {
        "id": "wikipedia-article",
        "name": "Wikipedia article",
        "description": "Significant content changes on a Wikipedia article.",
        "category": "research",
        "domain_hints": ["wikipedia.org"],
        "url_example": "https://en.wikipedia.org/wiki/Machine_learning",
        "extras": {
            "include_filters": ["#mw-content-text"],
            "subtractive_selectors": [".navbox", "#toc", ".reference", ".mw-editsection"],
            "use_page_title_in_list": True,
        },
    },
    {
        "id": "arxiv-new",
        "name": "arXiv — new submissions in a category",
        "description": "New papers posted in an arXiv category via its RSS feed.",
        "category": "research",
        "domain_hints": ["arxiv.org", "export.arxiv.org"],
        "url_example": "http://export.arxiv.org/rss/cs.AI",
        "extras": {
            "title": "arXiv new papers",
        },
    },

    # --- Jobs / status ---
    {
        "id": "job-board-generic",
        "name": "Job board listing",
        "description": "Alert when a company's 'Careers / Jobs' page lists new roles.",
        "category": "jobs",
        "domain_hints": [],
        "url_example": "https://example.com/careers",
        "extras": {
            "include_filters": ["main", "[role='main']", "#jobs", "#careers"],
            "subtractive_selectors": ["header", "footer", "nav", "script", "style"],
            "use_page_title_in_list": True,
        },
    },
    {
        "id": "status-page",
        "name": "Status page",
        "description": "Notify on any status change for a statuspage.io-style page.",
        "category": "status",
        "domain_hints": ["status.io", "statuspage.io"],
        "url_example": "https://status.example.com/",
        "extras": {
            "include_filters": [".status-summary", ".overall-status", ".component-inner-container"],
            "trigger_text": ["/(?i)(outage|degraded|partial|major|incident)/"],
            "title": "Status page",
        },
    },
    {
        "id": "notion-changelog",
        "name": "Notion / docs changelog",
        "description": "Generic 'Changelog' / 'What's new' page monitoring.",
        "category": "dev",
        "domain_hints": [],
        "url_example": "https://www.example.com/changelog",
        "extras": {
            "include_filters": ["main", "article", ".changelog"],
            "subtractive_selectors": ["header", "footer", "nav"],
            "use_page_title_in_list": True,
        },
    },
]


def get_recipe(recipe_id):
    """Return the recipe dict with id == recipe_id, or None."""
    for r in RECIPES:
        if r["id"] == recipe_id:
            return r
    return None


def recipes_by_category():
    """Group recipes into an ordered dict of category -> [recipe, …]."""
    from collections import OrderedDict
    order = ["shopping", "dev", "news", "social", "research", "jobs", "status"]
    buckets = OrderedDict((c, []) for c in order)
    buckets["other"] = []
    for r in RECIPES:
        buckets.setdefault(r.get("category", "other"), []).append(r)
    # drop empty
    return OrderedDict((k, v) for k, v in buckets.items() if v)
