# Extra Playwright Servers

Connect changedetection.io to **additional self-hosted browser servers** and
choose which one to use on a per-watch basis. This is useful for running
browsers in different geolocations, with different configurations, or simply to
spread fetching load across several browser containers.

Each configured server appears as a selectable **Fetch Method** when editing a
watch (alongside the built-in "Chrome/Javascript", "Plain requests", etc.).

## Configuring servers

1. Go to **Settings → Captcha/Proxies → Extra Playwright Servers**.
2. For each server, enter:
   - **Name** – a label (e.g. `US-East`). This is what you'll pick in the
     Fetch Method dropdown.
   - **Playwright server URL** – the browser server's websocket address. It
     must start with `ws://` or `wss://`.
3. **Save**.

Then, per watch: **Edit → Request → Fetch Method →** select your server, save,
and recheck.

## URL format and what counts as a compatible server

changedetection.io connects to the server with Playwright's
[`connect_over_cdp()`](https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp),
which speaks the **Chrome DevTools Protocol (CDP)** over a websocket and connects
to the **root path** (`/`) of the URL you provide.

A compatible server is therefore a **CDP gateway** that accepts a connection at
`/` and returns a browser session. Two well-supported options:

| Server | Example URL | Notes |
| --- | --- | --- |
| [browserless](https://github.com/browserless/browserless) | `ws://my-browserless:3000?token=YOURTOKEN` | Token configured via the `TOKEN` env var |
| [sockpuppetbrowser](https://github.com/dgtlmoon/sockpuppetbrowser) | `ws://my-sockpuppet:3000` | changedetection.io's own browser server |

Connection options can be passed as query string parameters where the server
supports them, e.g. `ws://my-server:3000/?stealth=1`.

### Not compatible: the `microsoft/playwright` image

The upstream [microsoft/playwright](https://github.com/microsoft/playwright)
image cannot be used as a server for this feature:

- `npx playwright run-server` speaks the **Playwright** wire protocol (a client
  would use `connect()`), **not** CDP, so it is incompatible with
  `connect_over_cdp()`.
- Running raw Chrome from that image with `--remote-debugging-port` doesn't work
  either: Chrome binds the debug port to `127.0.0.1` only, its CDP endpoint
  lives at a dynamic `/devtools/browser/<guid>` path (so the root `/` returns
  `404`), and its DNS-rebinding protection rejects non-localhost `Host` headers.

Use browserless or sockpuppetbrowser instead.

## Try it locally

A ready-made test stack is provided at
[`docker-compose.test-playwright.yml`](../docker-compose.test-playwright.yml). It
starts changedetection.io plus a browserless and a sockpuppetbrowser server:

```bash
docker compose -f docker-compose.test-playwright.yml up -d
```

Then add the two servers in Settings using the URLs printed in that file's
comments.

## How it works internally

- Configured servers are stored under
  `settings.requests.extra_playwright_servers` in the datastore.
- Each server is offered as a `extra_playwright_server_<name>` fetch-backend
  choice in the watch edit form.
- When a watch uses one, `processors/base.py` looks up the URL and **forces the
  Playwright fetcher** (so screenshots, browser steps and the visual selector
  all work), connecting to the configured server instead of the default
  `PLAYWRIGHT_DRIVER_URL`.
