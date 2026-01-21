# Site-Specific Issues and Workarounds

This document contains known issues, workarounds, special configurations, anti-bot escalation recommendations, and working CSS selectors for each tested ticketing site.

**Last Updated:** 2026-01-21
**Related User Stories:** US-016, US-017, US-018, US-019

---

## Table of Contents

1. [metrotixchicago.com](#metrotixchicagocom)
2. [thaliahall.com](#thaliahallcom)
3. [etix.com](#etixcom)
4. [General Recommendations](#general-recommendations)

---

## metrotixchicago.com

### Overview

MetroTix Chicago is the primary ticketing platform for many Chicago-area venues including Historic Theatre Chicago, Chicago Music Hall, and Riviera Theatre.

### Known Issues

| Issue | Description | Severity | Status |
|-------|-------------|----------|--------|
| **JS-rendered content** | Event pages require JavaScript execution to fully render ticket options and prices | Medium | Mitigated with Playwright |
| **Hidden CSS elements** | Raw HTML parsing cannot distinguish CSS `display:none` elements from visible content | Low | Documented behavior |
| **Dynamic pricing** | Prices may be loaded via AJAX after initial page load | Medium | Mitigated with Playwright wait strategies |
| **Session-based access** | Some event pages may require active session cookies | Low | Monitor for issues |

### Workarounds and Special Configurations

```yaml
# Recommended watch configuration for metrotixchicago.com
watch_config:
  fetch_method: playwright  # Required for JS-rendered content
  check_interval: 300       # 5 minutes (respect rate limits)
  wait_time: 3000           # Wait 3s for JS to execute
  selector_wait: ".ticket-section"  # Wait for ticket section to appear

# Playwright-specific settings
playwright_config:
  headless: true
  wait_until: networkidle
  timeout: 30000
```

**Important Notes:**
- Always use `playwright` fetch method - `requests` will not capture dynamic prices
- Wait for `.ticket-section` to ensure prices are loaded
- Service fees are displayed separately and should not be parsed as prices

### Anti-Bot Escalation Recommendations

| Escalation Level | Indicators | Recommended Actions |
|-----------------|------------|---------------------|
| **Level 1** | Standard page loads normally | Normal operation with 5-minute intervals |
| **Level 2** | Occasional timeouts or empty responses | Increase check interval to 10 minutes, add random jitter (0-60s) |
| **Level 3** | CAPTCHA challenges appearing | Implement rotating user agents, consider residential proxies |
| **Level 4** | IP blocks | Switch to proxy rotation, implement exponential backoff |

**Current Status:** Level 1 - No anti-bot measures detected as of testing date

### Working CSS Selectors

```css
/* Event Information */
.event-header .event-title          /* Event name */
.event-venue .venue-name            /* Venue name */
.event-venue .venue-address         /* Venue address */
.event-details .event-date          /* Event date */
.event-details .event-time          /* Event time */

/* Ticket Pricing */
.ticket-section                     /* Container for all ticket options */
.ticket-option                      /* Individual ticket type row */
.ticket-option .ticket-type         /* Ticket type name (GA, VIP, etc.) */
.ticket-option .ticket-price        /* Price display (e.g., "$35.00") */
.ticket-option .availability        /* Availability status text */

/* Price Range (for multi-tier events) */
.price-range .range                 /* Price range display (e.g., "$75 - $350") */
.ticket-tiers .tier                 /* Individual tier with embedded price */

/* Availability Status */
.sold-out-notice                    /* Sold out container */
.sold-out-notice h2                 /* "SOLD OUT" text */
.urgency-notice                     /* Limited availability warning */
.urgency-notice .urgency-text       /* "Only X tickets left!" text */
.waitlist-section .waitlist-button  /* Waitlist button (indicates sold out) */

/* Purchase Actions */
.purchase-section .buy-button       /* Primary purchase button */
.service-fee                        /* Service fee notice (ignore for price) */
```

### Extraction Notes

- **Price Format:** `$XX.00` - Always includes cents
- **Currency:** USD only
- **Price Types:** Single prices per ticket tier
- **Availability Indicators:**
  - `Available` - In stock
  - `Limited Availability` - Low stock
  - `SOLD OUT` - Out of stock
  - Presence of waitlist button indicates sold out

---

## thaliahall.com

### Overview

Thalia Hall is a historic venue in Chicago's Pilsen neighborhood. The website uses a relatively standard HTML structure with optional JavaScript enhancements.

### Known Issues

| Issue | Description | Severity | Status |
|-------|-------------|----------|--------|
| **Mixed availability signals** | Pages may show both "Sold Out" (for one tier) and "Buy Tickets" (for another) | Medium | Documented - conservative approach taken |
| **Hidden past event data** | Past event prices/statuses may be in hidden DOM elements | Low | Documented behavior |
| **21+ age restrictions** | Age restrictions (21+) should not be parsed as prices | Low | Handled by price extractor |
| **Doors/Show time format** | Unique time format "Doors: X PM / Show: Y PM" | Low | Informational only |

### Workarounds and Special Configurations

```yaml
# Recommended watch configuration for thaliahall.com
watch_config:
  fetch_method: playwright  # Recommended for consistent rendering
  check_interval: 300       # 5 minutes
  wait_time: 2000           # Wait 2s for page load
  selector_wait: ".ticket-info"  # Wait for ticket info section

# Alternative: requests method may work for static pages
alt_watch_config:
  fetch_method: requests    # May work for simpler pages
  check_interval: 300
```

**Important Notes:**
- The availability detector takes a conservative approach - if ANY tier shows "Sold Out", it will report `out_of_stock`
- This is intentional to ensure users are alerted to partial sellouts
- 21+ age restriction text is filtered out by the price extractor

### Anti-Bot Escalation Recommendations

| Escalation Level | Indicators | Recommended Actions |
|-----------------|------------|---------------------|
| **Level 1** | Standard page loads normally | Normal operation with 5-minute intervals |
| **Level 2** | Rate limiting (429 responses) | Increase check interval to 10-15 minutes |
| **Level 3** | Cloudflare challenge page | Use Playwright with stealth plugin, add delays |
| **Level 4** | Persistent blocks | Contact venue for API access or use official ticket alerts |

**Current Status:** Level 1 - No anti-bot measures detected as of testing date

### Working CSS Selectors

```css
/* Event Information */
.event-page .event-hero             /* Event header container */
.event-hero .event-title            /* Event name */
.event-meta .event-date             /* Event date */
.event-meta .event-time             /* Time (Doors/Show format) */

/* Venue Information */
.venue-details h2                   /* Venue name ("Thalia Hall") */
.venue-details address              /* Full address */

/* Ticket Pricing */
.ticket-info                        /* Container for ticket options */
.price-tier                         /* Individual ticket tier row */
.price-tier .tier-name              /* Tier name (GA, Balcony, VIP) */
.price-tier .tier-price             /* Price display */
.price-tier .fee-note               /* Fee notice (filter out) */

/* Price Range/Summary */
.price-summary                      /* Price range container */
.price-summary .price-range         /* Range display (e.g., "$40 - $150") */

/* Availability Status */
.ticket-info.sold-out               /* Sold out ticket section */
.sold-out-banner                    /* Sold out banner container */
.sold-out-banner .sold-out-text     /* "SOLD OUT" text */
.sold-out-message                   /* Sold out explanation */
.urgency-banner                     /* Limited availability warning */
.urgency-banner .urgency-message    /* "Only X tickets remaining!" */
.availability-status                /* Per-tier status (e.g., "Almost sold out") */

/* Purchase Actions */
.ticket-actions                     /* Action buttons container */
.buy-tickets-btn                    /* Primary purchase button */
.join-waitlist-btn                  /* Waitlist button (indicates sold out) */

/* Age Restrictions (filter out) */
.age-restriction                    /* "21+ Event" text - DO NOT parse as price */
```

### Extraction Notes

- **Price Format:** `$XX.00` - Always includes cents
- **Currency:** USD only
- **Time Format:** "Doors: X PM / Show: Y PM" unique to Thalia Hall
- **Availability Indicators:**
  - "Buy Tickets" button - In stock
  - "Almost sold out" - Limited
  - "Only X tickets remaining!" - Limited
  - "SOLD OUT" banner - Out of stock
  - "Join Waitlist" button - Out of stock

---

## etix.com

### Overview

Etix is a national ticketing platform used by various venues including Downtown Arena (Austin), The Fillmore (San Francisco), Blue Note Jazz Club (New York), and many others.

### Known Issues

| Issue | Description | Severity | Status |
|-------|-------------|----------|--------|
| **Multiple date handling** | Events with multiple dates may show mixed availability per date | Medium | Documented - conservative approach |
| **"On Sale" vs "On Sale Now"** | Pattern matching requires exact "On Sale Now" for in_stock detection | Low | Documented pattern |
| **Dynamic content sections** | Hidden `style="display:none"` sections may contain old sold out text | Low | Documented behavior |
| **Resale integration** | "View Resale" button appears on sold out events | Low | Informational |
| **Rate limiting** | May require proxy rotation for high-frequency monitoring | Medium | Proxy support available |

### Workarounds and Special Configurations

```yaml
# Recommended watch configuration for etix.com
watch_config:
  fetch_method: requests    # Static pages generally work without JS
  check_interval: 300       # 5 minutes

# For JS-heavy pages or anti-bot issues
playwright_config:
  fetch_method: playwright
  check_interval: 300
  wait_time: 2000

# Proxy rotation configuration (if needed)
proxy_config:
  proxy_enabled: true
  proxy_rotation: round_robin  # Options: round_robin, random, weighted
  proxy_list_path: /data/proxies.txt
  proxy_health_check: true
```

**Important Notes:**
- Etix pages generally work with simple `requests` fetching
- If rate limiting occurs, enable proxy rotation
- "On Sale" status text does NOT trigger in_stock - requires "On Sale Now"
- "Few Left" or "Almost Sold Out" correctly triggers limited status

### Anti-Bot Escalation Recommendations

| Escalation Level | Indicators | Recommended Actions |
|-----------------|------------|---------------------|
| **Level 1** | Standard page loads normally | Normal operation with requests method |
| **Level 2** | Intermittent 403 or empty responses | Switch to Playwright, add random delays |
| **Level 3** | Rate limiting (429 responses) | Enable proxy rotation, increase intervals to 10-15 min |
| **Level 4** | IP blocks or CAPTCHA | Use residential proxies, implement browser fingerprint rotation |

**Current Status:** Level 1 - No anti-bot measures detected as of testing date

### Working CSS Selectors

```css
/* Event Information */
.event-container                    /* Main event wrapper */
.event-header .event-name           /* Event name */
.event-info .venue                  /* Venue name */
.event-info .location               /* City, State */
.event-datetime .date               /* Event date */
.event-datetime .time               /* Event time */

/* Ticket Pricing */
.ticket-types                       /* Container for ticket options */
.ticket-row                         /* Individual ticket type row */
.ticket-row .ticket-name            /* Ticket type name */
.ticket-row .ticket-price           /* Price display */
.ticket-row .availability-status    /* Status (On Sale, Limited, etc.) */
.ticket-row .plus-fees              /* Fee notice (filter out) */

/* Multi-date events */
.show-dates                         /* Container for date options */
.date-option                        /* Individual date row */
.date-option .date                  /* Date and time */
.date-option .price                 /* Price for this date */
.date-option .status                /* Availability for this date */

/* Price Range/Summary */
.pricing-overview                   /* Price summary container */
.pricing-overview .price-range      /* Range container */
.price-range .range                 /* Range display (e.g., "$95 - $499") */

/* Availability Status */
.sold-out-banner                    /* Sold out container */
.sold-out-banner .sold-out-text     /* "SOLD OUT" text */
.sold-out-message                   /* Sold out explanation */
.urgency-banner                     /* Limited availability warning */
.urgency-banner .urgency-message    /* "Hurry! Only X tickets remaining!" */
.ticket-status                      /* General status container */

/* Purchase Actions */
.ticket-row .buy-btn                /* Individual tier buy button */
.buy-now-btn                        /* Urgent purchase button */
.add-to-cart                        /* Add to cart button */
.select-tickets                     /* Multi-date selection button */
.purchase-section                   /* Purchase container */

/* Sold Out Alternatives */
.secondary-market                   /* Resale options container */
.resale-btn                         /* "View Resale" button (indicates sold out) */
```

### Extraction Notes

- **Price Format:** `$XX.00` - Always includes cents
- **Currency:** USD only
- **URL Format:** `https://www.etix.com/ticket/p/{event_id}/{event-slug}`
- **Availability Indicators:**
  - "On Sale" (generic) - Unknown (pattern requires "On Sale Now")
  - "On Sale Now" - In stock
  - "Limited", "Few Left", "Almost Sold Out" - Limited
  - "SOLD OUT" banner - Out of stock
  - "View Resale" button - Out of stock
  - "Hurry!" or "Only X remaining" - Limited

---

## General Recommendations

### Fetch Method Selection Guide

| Site Pattern | Recommended Method | Reason |
|--------------|-------------------|--------|
| Static HTML with prices visible | `requests` | Faster, lower resource usage |
| JavaScript-rendered prices | `playwright` | Required for dynamic content |
| SPA (Single Page Application) | `playwright` | Full JS execution needed |
| API-based pricing | Custom API integration | Most reliable if available |

### Rate Limiting Best Practices

1. **Minimum interval:** 5 minutes between checks for the same URL
2. **Random jitter:** Add 0-60 seconds random delay to avoid patterns
3. **Exponential backoff:** On errors, double wait time up to 1 hour max
4. **Peak avoidance:** Consider reducing frequency during peak hours

### Proxy Configuration

```yaml
# Standard proxy configuration
proxy:
  enabled: false              # Enable when needed
  rotation: round_robin       # round_robin, random, weighted
  types:
    - datacenter              # Fast, may be detected
    - residential             # Slower, less detection
  health_check_interval: 300  # Check proxy health every 5 min
  fail_threshold: 3           # Mark proxy as bad after 3 failures
  recovery_time: 3600         # Try bad proxies again after 1 hour
```

### Hidden Content Handling

The availability detector processes raw HTML text, which includes content in `display:none` elements. This can cause:

- **False sold out signals** from hidden historical data
- **Conflicting signals** when one tier is sold out but others available

**Mitigation strategies:**
1. The detector prioritizes high-confidence sold out patterns (0.95+)
2. Conservative approach alerts on ANY sold out signal
3. Consider using Playwright's `page.textContent()` for visible text only

### CSS Selector Maintenance

When site layouts change:

1. **Check test files first** - Sample HTML in test files shows expected structure
2. **Use browser DevTools** - Inspect live pages for current selectors
3. **Update both** - Keep test HTML and selectors in sync
4. **Version selectors** - Consider maintaining selector versions for A/B tests

### Confidence Thresholds

| Status | Minimum Confidence | Action |
|--------|-------------------|--------|
| `out_of_stock` | 0.80 | High priority - send alert |
| `limited` | 0.75 | Medium priority - send alert |
| `in_stock` | 0.75 | Confirmation only |
| `unknown` | < 0.75 | Log for review, no alert |

---

## Appendix: Test Coverage Summary

| Site | Test File | Tests | Coverage |
|------|-----------|-------|----------|
| metrotixchicago.com | `test_metrotixchicago_integration.py` | 52 | All acceptance criteria |
| thaliahall.com | `test_thaliahall_integration.py` | 52 | All acceptance criteria |
| etix.com | `test_etix_integration.py` | 58 | All acceptance criteria |

All tests validate:
- Watch can be added for site event pages
- Content loads correctly (JS-rendered or static)
- Price extraction works correctly
- Changes trigger appropriate Slack alerts
