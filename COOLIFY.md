# Deploying onChange by Sairo on Coolify

This guide walks you through deploying **onChange by Sairo** on a
[Coolify](https://coolify.io) server (v4.x, tested against 2025/2026
releases). It assumes you already have a Coolify instance running with a
configured server, proxy (Traefik or Caddy), and a Git source connected.

> **TL;DR**
> 1. Create a new resource → **Docker Compose** → point at this repo.
> 2. Set the compose file path to `docker-compose.coolify.yml`.
> 3. Fill in the environment variables from the table below.
> 4. Click **Deploy**. Coolify provisions a domain, TLS, and a persistent
>    `/datastore` volume for you.

---

## 1. Prerequisites

| Thing | Minimum | Notes |
|---|---|---|
| Coolify | v4.0.0-beta.400 or newer (2025+) | v4.x is the only supported line |
| Server RAM | 1 GB | 2 GB+ if you enable the Playwright sidecar |
| Server disk | 2 GB free | Snapshots + screenshots grow over time |
| Domain | 1 subdomain | e.g. `onchange.yourdomain.com` with an `A`/`AAAA` record at your Coolify server |
| Git access | GitHub App, GitLab, or generic Git | Used for auto-deploy webhooks |

Coolify will terminate TLS for you via Let's Encrypt; you do **not** need to
set `SSL_CERT_FILE` / `SSL_PRIVKEY_FILE` unless you terminate TLS inside the
container yourself.

---

## 2. Create the resource

1. In the Coolify UI: **Projects → + New → Public or Private Repository**.
2. Pick the branch you want to deploy from (e.g. `main`).
3. **Build Pack:** *Docker Compose*.
4. **Docker Compose Location:** `docker-compose.coolify.yml`.
5. **Base Directory:** leave blank (repo root).
6. Click **Continue**.

Coolify will parse the compose file and show you the environment variables
referenced inside it on the next screen.

### Why a second compose file?

The root [`docker-compose.yml`](./docker-compose.yml) is tuned for local
`docker compose up` and binds the published port to `127.0.0.1:5000`.
[`docker-compose.coolify.yml`](./docker-compose.coolify.yml) uses Coolify's
[magic variables](https://coolify.io/docs/knowledge-base/docker/compose)
(`SERVICE_FQDN_*`, `SERVICE_URL_*`) so the proxy can wire a public domain to
the container, and it only **exposes** port 5000 internally — Coolify strongly
discourages using `ports:` inside compose because the proxy owns public
ingress.

---

## 3. Domain & TLS

Coolify auto-generates `SERVICE_FQDN_CHANGEDETECTION_5000` the first time
you deploy. To change it to your own domain:

1. Go to the resource → **Domains** tab.
2. Set `https://onchange.yourdomain.com:5000` (the `:5000` tells the proxy
   which internal container port to forward to; the public port is still
   443/80).
3. Save. Coolify will request a Let's Encrypt certificate automatically.

DNS: point an `A`/`AAAA` record at your Coolify server's public IP **before**
you save the domain, otherwise the ACME HTTP-01 challenge will fail.

---

## 4. Environment variables

All variables are documented in
[`.env.example`](./.env.example) — the short summary below lists the ones you
will most likely need on Coolify. Paste them into the resource's
**Environment Variables** tab.

### 4.1 Required

| Variable | Where it comes from | Notes |
|---|---|---|
| `SERVICE_FQDN_CHANGEDETECTION_5000` | **Auto — Coolify** | Do not edit; Coolify fills this from the Domain you set in step 3. |
| `BASE_URL` | `${SERVICE_URL_CHANGEDETECTION_5000}` | Already wired in `docker-compose.coolify.yml`. Used in notification/RSS links. |

### 4.2 Recommended

| Variable | Default | Why |
|---|---|---|
| `TZ` | `UTC` | Set to your local IANA zone so scheduled digests fire at the right hour. |
| `HIDE_REFERER` | `true` | Prevents monitored sites from learning your Coolify hostname. |
| `DISABLE_VERSION_CHECK` | `true` | No telemetry pings leave the instance. |
| `USE_X_SETTINGS` | `1` | Trust Coolify's Traefik/Caddy `X-Forwarded-*` headers. |
| `FETCH_WORKERS` | `10` | Drop to `4–6` on a 1 GB server, raise to `20+` on beefier hosts. |
| `LOGGER_LEVEL` | `INFO` | Use `DEBUG` only when troubleshooting. |

### 4.3 Optional features

#### 4.3.1 Admin-UI password (recommended if the instance is public)

Two options:

- **Set from inside the app:** leave `SALTED_PASS` unset, then go to
  **Settings → General → Password** after the first boot.
- **Set via Coolify magic:** in the compose file, uncomment:
  ```yaml
  - SALTED_PASS=${SERVICE_PASSWORD_64_CHANGEDETECTION}
  ```
  Coolify will generate a 64-char random password on first deploy and store
  it. You can read it back from the **Environment Variables** tab. (Note:
  `SALTED_PASS` must be the *hashed* form — use this only if you don't care
  about logging in via the UI and will call the API with the raw password.
  For human logins, prefer option 1.)

#### 4.3.2 AI-assisted filter builder

The "describe what to monitor in plain English" feature calls the Anthropic
Claude API.

| Variable | Where to get it | Cost |
|---|---|---|
| `ANTHROPIC_API_KEY` | <https://console.anthropic.com/settings/keys> | Pay-per-call; each filter suggestion uses a few thousand tokens. A cap of ~$5/month is plenty for personal use. |
| `AI_FILTER_MAX_HTML_CHARS` | — | Upper bound on HTML sent to Claude. Default `20000` (~5 kB of tokens). |

Leave `ANTHROPIC_API_KEY` blank to hide the feature completely.

#### 4.3.3 Outbound proxy

If your Coolify server must reach the internet through a proxy:

| Variable | Example |
|---|---|
| `HTTP_PROXY` | `socks5h://10.10.1.10:1080` |
| `HTTPS_PROXY` | `socks5h://10.10.1.10:1080` |
| `NO_PROXY` | `localhost,127.0.0.1,10.0.0.0/8` |

#### 4.3.4 JavaScript-rendered pages (Playwright sidecar)

Many modern sites need a real browser. To enable:

1. In `docker-compose.coolify.yml`, uncomment the `playwright-chrome`
   service block at the bottom.
2. Uncomment the `depends_on` block and the `PLAYWRIGHT_DRIVER_URL`
   environment line on the `changedetection` service.
3. Re-deploy.

The sidecar adds ~500 MB RAM to the resource. Coolify will show both
containers in the resource's **Logs** tab.

#### 4.3.5 SMTP / Apprise notifications

Notifications are configured from inside the app (**Settings → Notifications**)
using [Apprise URLs](https://github.com/caronc/apprise/wiki). No env vars
are required for this; your SMTP credentials live inside the datastore.

If you want a URL prefix on the "View change" button inside emails, set
`NOTIFICATION_MAIL_BUTTON_PREFIX`.

---

## 5. Persistent storage

`docker-compose.coolify.yml` mounts a named Docker volume at `/datastore`:

```yaml
volumes:
  - changedetection-data:/datastore
```

Coolify shows this on the **Storage** tab. Snapshots, screenshots, and the
`url-watches.json` index all live here. Back this up regularly — the built-in
backup feature (**More → Backup**) writes to the same volume, so you should
also copy those archives off-host (e.g. via the Coolify S3 backups feature).

> **Why not a bind mount?** Coolify's bind-mount code has a couple of
> outstanding bugs around files-vs-directories
> ([#6056](https://github.com/coollabsio/coolify/issues/6056),
> [#8107](https://github.com/coollabsio/coolify/issues/8107)). Named volumes
> avoid the whole category.

---

## 6. Healthcheck

The compose file ships an inline healthcheck that polls
`http://127.0.0.1:5000/` with Python's stdlib every 30 s. Coolify reads the
Docker health status and flags the container red if it fails three probes in
a row.

(Coolify's UI healthcheck panel is hidden for compose deployments — see
[#6463](https://github.com/coollabsio/coolify/issues/6463) — which is why we
declare it in the compose file.)

---

## 7. Auto-deploy

If you connected the repo via the **GitHub App** integration, Coolify
creates the webhook for you. Pushes to your deployment branch will rebuild
and redeploy the resource. Toggle it under **Advanced → Auto Deploy**.

For generic Git sources, set a webhook secret under the Git Source settings
and add a webhook at your Git host pointing to
`https://<coolify-host>/webhooks/source/git/events`.

To skip a particular commit, include `[skip ci]` in the commit message.

---

## 8. Updating the image

- **Auto deploy:** push to the branch.
- **Manual:** click **Deploy** on the resource, or call the API:
  ```bash
  curl -X POST -H "Authorization: Bearer $COOLIFY_TOKEN" \
    "https://<coolify>/api/v1/deploy?uuid=<app_uuid>"
  ```

---

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `502 Bad Gateway` from Traefik | The container is still starting; wait for the healthcheck to go green. If it never does, check **Logs** for a Python traceback. |
| Notifications/RSS show `http://localhost:5000` instead of your domain | `BASE_URL` is not being populated. Confirm the domain is saved on the **Domains** tab and redeploy (this refreshes `SERVICE_URL_*`). |
| `ssrf` / "restricted address" errors fetching a page | The target resolved to a private IP. Only override `ALLOW_IANA_RESTRICTED_ADDRESSES=true` if you trust the target. |
| OOM kills with Playwright enabled | Lower `FETCH_WORKERS`, or upgrade the server. Playwright + Chromium needs ~500 MB per concurrent browser. |
| Screenshots truncated | Raise `SCREENSHOT_MAX_HEIGHT` (watch RAM usage). |
| Build fails on `cryptography` wheel | Usually a transient piwheels mirror problem. Re-deploy; the Dockerfile already has ARM fallbacks baked in. |

---

## 10. Reference

- [`.env.example`](./.env.example) — every env var the app reads, documented.
- [`docker-compose.coolify.yml`](./docker-compose.coolify.yml) — the compose
  file Coolify uses.
- [`Dockerfile`](./Dockerfile) — non-root runtime, multi-stage build.
- [Coolify Docker Compose docs](https://coolify.io/docs/knowledge-base/docker/compose)
- [Coolify environment variables](https://coolify.io/docs/knowledge-base/environment-variables)
- [Coolify healthchecks](https://coolify.io/docs/knowledge-base/health-checks)
- [Coolify persistent storage](https://coolify.io/docs/knowledge-base/persistent-storage)

Questions, bugs, or improvements? Open an issue on **this** repo, not
upstream. See [`CONTRIBUTING.md`](./CONTRIBUTING.md).
