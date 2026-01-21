# Product Requirements Document: TicketWatch
## Custom Ticket Monitoring Platform (changedetection.io Fork)

---

## 1. Executive Summary

**Product Name:** TicketWatch (working title)

**Vision:** A self-hosted ticket monitoring platform forked from changedetection.io, optimized for tracking ticket availability, pricing, and sellouts across venue ticketing sites (Etix, Prekindle, TicketWeb, etc.), with custom Slack notifications and future integration with existing ticket data systems.

**Target Users:** Internal use - monitoring ticket sales for events at venues using platforms like metrotixchicago.com, thaliahall.com, and similar ticketing providers.

---

## 2. Goals & Success Metrics

### Primary Goals
1. Successfully monitor 200+ events across multiple ticketing platforms
2. Extract and alert on ticket prices and price ranges
3. Deliver customized Slack notifications with relevant event context
4. Run reliably on Fly.io with Neon.tech database backend

### MVP Success Criteria
- [ ] Monitor at least 3 test sites (metrotixchicago.com, thaliahall.com, + 1 other)
- [ ] Successfully detect and alert on price changes or sellouts
- [ ] Slack messages delivered to configured channel
- [ ] Stable deployment on Fly.io for 1 week without intervention

---

## 3. Scope

### Phase 1: MVP (This PRD)
- Fork and deploy changedetection.io to Fly.io
- Configure Neon.tech PostgreSQL as data store
- Implement proxy rotation from provided lists
- Basic Slack integration with custom formatting
- Browser extension functional for self-hosted instance
- Test against target ticketing sites

### Phase 2: Enhanced Extraction (Future)
- Advanced price/inventory extraction with site-specific parsers
- Historical data tracking (added date, sellout date, inventory over time)
- Richer Slack formatting with event metadata

### Phase 3: Full Integration (Future)
- Inject ticket data from existing Neon.tech database
- Multi-channel Slack routing based on event type/venue
- Per-user notification preferences
- Interactive Slack buttons (snooze, mark tracked, etc.)
- API for React/Next.js site integration
- Full anti-bot escalation (Selenium, fingerprint rotation)

### Out of Scope (For Now)
- UI embedding in existing site
- Real-time inventory count tracking
- Automated ticket purchasing
- Public-facing features

---

## 4. Technical Architecture

### 4.1 Infrastructure

| Component | Technology | Notes |
|-----------|------------|-------|
| **Hosting** | Fly.io | App: `changedetection-io-z08mj` (fresh setup) |
| **Database** | Neon.tech (PostgreSQL) | Replace file-based storage |
| **Proxy** | User-provided proxy lists | Rotating residential/datacenter proxies |
| **Browser Automation** | Playwright (built-in) → Selenium (future) | Start with Playwright, escalate if needed |
| **Notifications** | Slack API | Custom bot with rich formatting |

### 4.2 Deployment Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      Fly.io                             │
│  ┌─────────────────────────────────────────────────┐   │
│  │           TicketWatch (Fork)                     │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │   │
│  │  │  Web UI  │  │  Worker  │  │  Playwright  │  │   │
│  │  │  :5000   │  │  Engine  │  │  Browser     │  │   │
│  │  └──────────┘  └──────────┘  └──────────────┘  │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
          │                              │
          ▼                              ▼
┌──────────────────┐           ┌──────────────────┐
│   Neon.tech      │           │   Proxy Pool     │
│   PostgreSQL     │           │   (User Lists)   │
└──────────────────┘           └──────────────────┘
          │
          ▼
┌──────────────────┐
│   Slack API      │
│   (Webhooks)     │
└──────────────────┘
```

### 4.3 Database Schema (MVP)

```sql
-- Core watch configuration (migrated from file storage)
CREATE TABLE watches (
    id UUID PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT,
    tag TEXT[],
    check_interval INTEGER DEFAULT 3600,
    last_checked TIMESTAMP,
    last_changed TIMESTAMP,
    paused BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Change history
CREATE TABLE snapshots (
    id UUID PRIMARY KEY,
    watch_id UUID REFERENCES watches(id),
    content_hash TEXT,
    captured_at TIMESTAMP DEFAULT NOW(),
    -- MVP: store raw extracted data
    extracted_prices JSONB,
    extracted_availability TEXT
);

-- Future: Link to external ticket data
-- CREATE TABLE ticket_enrichment (
--     watch_id UUID REFERENCES watches(id),
--     external_event_id TEXT,
--     custom_name TEXT,
--     notes TEXT
-- );
```

### 4.4 Proxy Configuration

```yaml
# proxy_config.yaml
proxy_pools:
  default:
    type: rotating
    sources:
      - file: /app/proxies/residential.txt
      - file: /app/proxies/datacenter.txt
    rotation: per_request
    
  # Future: per-site escalation
  aggressive:
    type: rotating
    browser: playwright
    fingerprint_rotation: true
```

---

## 5. Functional Requirements

### 5.1 Core Monitoring (MVP)

| ID | Requirement | Priority |
|----|-------------|----------|
| M-01 | Monitor URLs at configurable intervals (1min - 24hr) | P0 |
| M-02 | Detect content changes on target pages | P0 |
| M-03 | Support CSS selector-based content targeting | P0 |
| M-04 | Rotate through proxy list for requests | P0 |
| M-05 | Use Playwright for JavaScript-rendered pages | P1 |
| M-06 | Browser extension works with self-hosted instance | P1 |

### 5.2 Data Extraction (MVP)

| ID | Requirement | Priority |
|----|-------------|----------|
| E-01 | Extract visible price text from pages | P0 |
| E-02 | Extract price ranges (e.g., "$25 - $75") | P0 |
| E-03 | Detect "Sold Out" / "Unavailable" states | P0 |
| E-04 | Store event name (manual input or page title) | P1 |
| E-05 | Extract ticket count/inventory (where visible) | P2 |

### 5.3 Slack Integration (MVP)

| ID | Requirement | Priority |
|----|-------------|----------|
| S-01 | Send alert to configured Slack channel on change | P0 |
| S-02 | Custom message format with event name, price, URL | P0 |
| S-03 | Different message templates for: new listing, price change, sellout | P1 |
| S-04 | Include screenshot attachment (optional) | P2 |

**MVP Slack Message Format:**
```
🎫 *Price Change Detected*
━━━━━━━━━━━━━━━━━━━
*Event:* {{ event_name }}
*Venue:* {{ venue }}
*Previous:* {{ old_price }}
*Current:* {{ new_price }}
*Status:* {{ availability }}
━━━━━━━━━━━━━━━━━━━
<{{ url }}|View Tickets>
```

### 5.4 Storage & Persistence (MVP)

| ID | Requirement | Priority |
|----|-------------|----------|
| D-01 | Store all watch configurations in Neon PostgreSQL | P0 |
| D-02 | Store change history/snapshots | P0 |
| D-03 | Store extracted price data as structured JSON | P1 |
| D-04 | Record date added and date of sellout | P1 |

---

## 6. Non-Functional Requirements

### 6.1 Performance
- Support 200+ concurrent watches
- Check interval minimum: 1 minute (respect site rate limits)
- Alert delivery within 60 seconds of detection

### 6.2 Reliability
- Auto-restart on failure (Fly.io health checks)
- Graceful handling of site blocks (log, retry with different proxy)
- Database connection pooling for Neon.tech

### 6.3 Security
- Proxy credentials stored as Fly.io secrets
- Slack webhook URL stored as secret
- No public exposure of admin UI (optional auth)

---

## 7. Target Sites & Challenges

| Site | Platform | Expected Challenges |
|------|----------|---------------------|
| metrotixchicago.com | Metro Tix | JS rendering, dynamic pricing |
| thaliahall.com | Eventbrite/Custom | May require login detection |
| Etix sites | Etix | Bot detection, Cloudflare |
| Prekindle sites | Prekindle | Dynamic content loading |
| TicketWeb sites | TicketWeb | Rate limiting |

**Anti-Bot Escalation Path:**
1. **Level 1 (MVP):** Rotating proxies + standard headers
2. **Level 2:** Playwright with realistic timing/scrolling
3. **Level 3:** Full fingerprint rotation (user agent, viewport, etc.)
4. **Level 4:** Selenium with undetected-chromedriver (future)

---

## 8. Browser Extension

The changedetection.io browser extension should work with self-hosted instances by configuring:
- Custom API endpoint URL (your Fly.io app URL)
- API key authentication

**Functionality needed:**
- Quick-add current page to watchlist
- Test/preview CSS selectors on page
- View element picker for targeting specific content

---

## 9. Implementation Phases

### Phase 1: MVP (Target: Get it Working)

**Step 1: Fork & Local Setup**
- [ ] Fork changedetection.io repository
- [ ] Set up local development environment
- [ ] Understand existing architecture and data flow

**Step 2: Database Migration**
- [ ] Create Neon.tech project and database
- [ ] Implement PostgreSQL adapter (replace file storage)
- [ ] Migrate existing data models to SQL schema
- [ ] Test data persistence

**Step 3: Fly.io Deployment**
- [ ] Create Dockerfile optimized for Fly.io
- [ ] Configure fly.toml with proper resources
- [ ] Set up secrets (DB connection, Slack webhook)
- [ ] Deploy and verify basic functionality

**Step 4: Proxy Integration**
- [ ] Implement proxy rotation middleware
- [ ] Load proxies from mounted file or environment
- [ ] Add proxy health checking (mark dead proxies)
- [ ] Test against target sites

**Step 5: Slack Customization**
- [ ] Create custom notification handler
- [ ] Implement message templates (price change, sellout, etc.)
- [ ] Add extracted price data to messages
- [ ] Test end-to-end alerting

**Step 6: Validation**
- [ ] Add watches for test sites
- [ ] Verify price extraction works
- [ ] Confirm Slack alerts fire correctly
- [ ] Document any site-specific issues

### Phase 2: Enhanced Features (Future)
- Historical price tracking and trends
- Site-specific parsers for better extraction
- Multi-channel Slack routing
- Inventory count monitoring

### Phase 3: Full Integration (Future)
- API for external access (React site)
- Ticket data enrichment from Neon.tech
- Per-user Slack notifications
- Interactive Slack components
- Advanced anti-bot measures

---

## 10. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Sites block our requests | High | High | Proxy rotation, escalation path to browser automation |
| Neon.tech adapter complexity | Medium | Medium | Start with minimal schema, migrate incrementally |
| Playwright resource usage on Fly.io | Medium | Medium | Configure appropriate VM size, use browser pooling |
| Price extraction unreliable | Medium | Medium | Allow manual selector configuration per watch |
| Extension doesn't work self-hosted | Low | Low | Extension is P1, can add watches via UI |

---

## 11. Open Questions

1. **Fly.io Resources:** What VM size is appropriate for Playwright + 200 watches?
2. **Proxy Format:** What format are the proxy lists in? (user:pass@host:port?)
3. **Slack Workspace:** Is there an existing Slack bot, or create new?
4. **Auth:** Should the web UI require authentication?
5. **Domain:** Will this run on a custom domain or Fly.io default?

---

## 12. Appendix

### A. Changedetection.io Key Files to Modify

```
changedetection.io/
├── changedetectionio/
│   ├── store.py           # → Replace with PostgreSQL adapter
│   ├── notification.py    # → Customize Slack formatting
│   ├── fetch_site_status.py  # → Add proxy rotation
│   └── processors/        # → Add price extraction logic
├── Dockerfile             # → Optimize for Fly.io
└── requirements.txt       # → Add psycopg2, etc.
```

### B. Fly.io Configuration Template

```toml
# fly.toml
app = "changedetection-io-z08mj"
primary_region = "ord"  # Chicago - close to target venues

[build]
  dockerfile = "Dockerfile"

[env]
  PLAYWRIGHT_BROWSERS_PATH = "/app/browsers"

[http_service]
  internal_port = 5000
  force_https = true

[[vm]]
  cpu_kind = "shared"
  cpus = 2
  memory_mb = 2048  # Playwright needs memory
```

### C. Environment Variables Needed

```bash
# Fly.io Secrets
DATABASE_URL=postgresql://user:pass@ep-xxx.us-east-2.aws.neon.tech/ticketwatch
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx
PROXY_LIST_PATH=/app/proxies/list.txt
# Optional
SALTED_PASS=xxx  # For web UI auth
```