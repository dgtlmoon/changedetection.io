# TicketWatch Architecture Documentation
## changedetection.io Codebase Overview

This document provides a comprehensive overview of the changedetection.io architecture to support customization for ticket monitoring (TicketWatch).

---

## 1. Application Entry Points

### Main Entry Point
- **File**: `changedetection.py` (root)
- **Purpose**: CLI wrapper that calls `changedetectionio.main()`

### Core Initialization
- **File**: `changedetectionio/__init__.py`
- **Function**: `main()`
- **Responsibilities**:
  - CLI argument parsing (datastore path, port, host, SSL, logging)
  - Directory setup (Windows: `%APPDATA%\changedetection.io`, Linux: `../datastore`)
  - Datastore initialization (loads JSON database)
  - Logger configuration (loguru with stdout/stderr separation)
  - Signal handlers (SIGTERM/SIGINT for graceful shutdown)
  - Flask app factory invocation

---

## 2. Core Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    USER/SCHEDULER                            │
└──────────────────────────┬──────────────────────────────────┘
                           │
                    ┌──────▼──────┐
                    │ Flask Routes │
                    └──────┬────────┘
                           │
    ┌──────────────────────┼──────────────────────┐
    │                      │                      │
    ▼                      ▼                      ▼
┌─────────┐          ┌──────────┐          ┌─────────┐
│ Add/Edit│          │  Trigger │          │Settings │
│ Watches │          │  Check   │          │Updates  │
└──────┬──┘          └────┬─────┘          └────┬────┘
       │                  │                     │
       └──────────────────┼─────────────────────┘
                          │
                   ┌──────▼───────────┐
                   │  RecheckPriority │
                   │     Queue        │
                   └──────┬───────────┘
                          │
    ┌─────────────────────┼─────────────────────┐
    │         ┌───────────┼───────────┐         │
    │         │           │           │         │
    ▼         ▼           ▼           ▼         ▼
┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
│Worker 1│ │Worker 2│ │Worker 3│ │  ...   │ │Worker N│
│(Async) │ │(Async) │ │(Async) │ │        │ │(Async) │
└───┬────┘ └───┬────┘ └───┬────┘ └────────┘ └────┬───┘
    │          │          │                     │
    └──────────┼──────────┼─────────────────────┘
               │          │
       ┌───────▼──────────▼──────────┐
       │  Content Fetchers           │
       │  (playwright/puppeteer/req) │
       └───────┬──────────┬──────────┘
               │          │
       ┌───────▼──────────▼──────────┐
       │  Processors                 │
       │  (text_json_diff/restock)   │
       └───────┬──────────┬──────────┘
               │          │
            ┌──▼──────────▼───┐
            │ Change Detected?│
            └──┬────────┬─────┘
               │No      │Yes
          ┌────▼──┐  ┌──▼────────────┐
          │ Update│  │Queue          │
          │History│  │Notification   │
          └───────┘  └──┬────────────┘
                        │
                 ┌──────▼──────┐
                 │Notification │
                 │ Runner      │
                 │ Thread      │
                 └──────┬──────┘
                        │
                ┌───────▼────────┐
                │  Apprise       │
                │  Dispatcher    │
                └───────┬────────┘
                        │
    ┌───────┬───────┬───▼────┬─────┬────┐
    ▼       ▼       ▼        ▼     ▼    ▼
  Email  Discord Slack  Telegram Gotify...
```

---

## 3. Key Modules & Files

### Storage & State Management

| File | Purpose |
|------|---------|
| `changedetectionio/store.py` | JSON persistence, watch CRUD, thread-safe state management |
| `changedetectionio/model/Watch.py` | Individual watch configuration model |
| `changedetectionio/model/App.py` | Global application configuration |

**ChangeDetectionStore Class** (`store.py`):
- Manages `url-watches.json` database
- Thread-safe with Lock() for concurrent access
- Watch CRUD: `add_watch()`, `delete()`, `clone()`, `update_watch()`
- Background save thread for periodic persistence
- Version management and backups

### Worker Processing

| File | Purpose |
|------|---------|
| `changedetectionio/async_update_worker.py` | Core async worker processing loop |
| `changedetectionio/worker_handler.py` | Worker pool management, health checks |
| `changedetectionio/queue_handlers.py` | Async/sync priority queue (janus-based) |

**async_update_worker()** (`async_update_worker.py`):
- One async worker per thread with isolated event loop
- Processes jobs from `RecheckPriorityQueue`
- Workflow: Get job → Load processor → Fetch content → Detect changes → Queue notifications

### Content Fetchers

| File | Backend Type | Use Case |
|------|--------------|----------|
| `content_fetchers/requests.py` | `html_requests` | Standard HTTP requests |
| `content_fetchers/playwright.py` | `html_webdriver` | Browser automation (JS-rendered pages) |
| `content_fetchers/puppeteer.py` | `html_webdriver` | Alternative browser automation |
| `content_fetchers/webdriver_selenium.py` | Legacy | Selenium support |

### Processors (Change Detection Engines)

| Processor | Location | Purpose |
|-----------|----------|---------|
| `text_json_diff` | `processors/text_json_diff/` | Default text/HTML/JSON comparison |
| `restock_diff` | `processors/restock_diff/` | E-commerce price/stock monitoring |
| `image_ssim_diff` | `processors/image_ssim_diff/` | Screenshot visual comparison |

**Processor Interface**:
- `perform_site_check()`: Core diff detection method
- `Watch` subclass: Custom watch configuration (optional)
- Metadata: `name`, `processor_description`, `list_badge_text`

### Notifications

| File | Purpose |
|------|---------|
| `changedetectionio/notification_service.py` | Notification context building, placeholder rendering |
| `changedetectionio/notification/handler.py` | Apprise-based notification distribution |

**Available Placeholders**:
- `{{base_url}}`, `{{watch_url}}`, `{{watch_title}}`
- `{{diff}}`, `{{diff_added}}`, `{{diff_removed}}`
- `{{screenshot}}`, `{{triggered_text}}`
- Timezone-aware timestamps

**Cascading Configuration**:
- Watch settings → Tag settings → Global settings

### Web UI & API

| File | Purpose |
|------|---------|
| `changedetectionio/flask_app.py` | Flask app factory, route registration |
| `changedetectionio/blueprint/` | URL-prefixed route groups |
| `changedetectionio/api/` | REST API resources |

**Blueprints**:
- `watchlist`: Main watch list UI
- `ui`: Watch controls
- `settings`: Global configuration
- `tags`: Tag management
- `rss`: RSS feed generation
- `browser_steps`: Browser automation steps
- `imports`: Watch/config imports

---

## 4. Data Storage Structure

### JSON Database (`url-watches.json`)

```json
{
  "watching": {
    "uuid-1": {
      "url": "https://example.com",
      "tags": ["tag-uuid-1"],
      "processor": "text_json_diff",
      "fetch_backend": "html_requests",
      "filters": [],
      "notification_format": "html",
      "notification_urls": ["discord://..."],
      "history": {"timestamp": "snapshot.br"}
    }
  },
  "settings": {
    "headers": {},
    "requests": {
      "timeout": 45,
      "workers": 10,
      "time_between_check": {}
    },
    "application": {
      "notification_body": "...",
      "notification_title": "...",
      "password": false,
      "tags": {}
    }
  }
}
```

### Datastore Directory Structure

```
datastore/
├── url-watches.json           # Main JSON database
├── url-watches-0-52-8.json    # Version backup
├── proxies.json               # Proxy configuration (optional)
├── secret.txt                 # Flask session secret
├── uuid-1/
│   ├── history.json           # Watch history metadata
│   ├── snapshots/
│   │   ├── 1234567890.br      # Brotli-compressed snapshot
│   │   └── 1234567891         # Uncompressed fallback
│   └── screenshot/
│       ├── last-screenshot.png
│       └── last-error-screenshot.png
└── uuid-2/
    └── ...
```

---

## 5. Threading & Async Model

### Thread Pool
1. **Main Thread**: Flask HTTP server
2. **Ticker Thread**: Schedules watches based on frequency
3. **Notification Runner**: Processes queued notifications (single-threaded)
4. **Version Checker**: Periodic version check (daemon)
5. **Worker Threads** (N × configurable): Each runs isolated async event loop

### Event Loop Model (Python 3.12+ safe)
- Each worker thread creates isolated event loop: `asyncio.new_event_loop()`
- Uses `get_context('spawn')` multiprocessing for browser processes
- Prevents deadlocks from multi-threaded parent process

---

## 6. Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `FETCH_WORKERS` | 10 | Number of async workers |
| `PORT` | 5000 | Listen port |
| `LISTEN_HOST` | 0.0.0.0 | Bind address |
| `BASE_URL` | - | External URL for notifications |
| `LOGGER_LEVEL` | DEBUG | Log verbosity |
| `PLAYWRIGHT_DRIVER_URL` | - | Playwright browser connection |
| `DEFAULT_FETCH_BACKEND` | html_requests | Default content fetcher |

---

## 7. Key Files for TicketWatch Customization

Based on the PRD, these files will need modification:

| File | Modification Purpose |
|------|---------------------|
| `store.py` | Replace with PostgreSQL adapter |
| `notification/handler.py` | Customize Slack formatting |
| `content_fetchers/*.py` | Add proxy rotation |
| `processors/` | Add price extraction logic |
| `Dockerfile` | Optimize for Fly.io |
| `requirements.txt` | Add psycopg2, etc. |

---

## 8. Local Development Setup

### Prerequisites
- Python 3.12+
- pip

### Quick Start

```bash
# Clone the fork
git clone https://github.com/thetimechain/changedetection.io.git
cd changedetection.io

# Install dependencies
pip install -r requirements.txt

# Run locally
python changedetection.py -d ./datastore -p 5000

# Access UI at http://127.0.0.1:5000
```

### Docker Development

```bash
# Using docker-compose
docker compose up -d

# Access UI at http://127.0.0.1:5000
```

### Running Tests

```bash
# Run test suite
pytest changedetectionio/tests/

# Run specific test
pytest changedetectionio/tests/test_notification.py -v
```

---

## 9. API Reference

Full REST API documentation available at:
- **Interactive Docs**: `/docs/api_v1/index.html`
- **OpenAPI Spec**: `docs/api-spec.yaml`

### Key Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/watch` | GET/POST | List/create watches |
| `/api/v1/watch/<uuid>` | GET/PUT/DELETE | CRUD single watch |
| `/api/v1/watch/<uuid>/history` | GET | Watch snapshots |
| `/api/v1/tags` | GET/POST | Tag management |
| `/api/v1/systeminfo` | GET | System status |

---

## 10. Next Steps for TicketWatch

1. **Phase 1 (MVP)**: See `tasks/prd-product-requirements-document-ticketwatch.md`
   - Database migration (PostgreSQL adapter)
   - Fly.io deployment
   - Proxy integration
   - Slack customization

2. **Key customization points identified**:
   - `store.py` → PostgreSQL storage adapter
   - `notification/handler.py` → Custom Slack templates
   - `processors/restock_diff/` → Enhanced price extraction
   - `content_fetchers/` → Proxy rotation middleware
