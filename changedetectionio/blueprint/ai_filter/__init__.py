"""
AI-assisted filter builder.

Exposes POST /ui/ai-filter/<uuid>/suggest — the user describes in plain English
what they want to monitor on a page; the endpoint fetches the latest snapshot
from the watch's history, trims it to a budget of HTML/text, and asks Claude to
propose a CSS/XPath filter + optional trigger_text / ignore_text.

Design notes
------------
* Transport: plain HTTPS to api.anthropic.com via `requests` (already a dep).
  No new package required.
* Key management: stored in datastore.data['settings']['application']
  under 'ai_filter_api_key'. Envvar ANTHROPIC_API_KEY is also honoured as a
  fallback so Docker-first users can skip the settings form entirely.
* Safety:
    - max HTML payload sent to the model is capped
      (AI_FILTER_MAX_HTML_CHARS env, default 20000)
    - rate-limit: reject if the last call from this user was <10s ago
    - response is JSON-only via strict prompt + a JSON-schema style section;
      the endpoint also defensively extracts the first {...} block
* UX: this endpoint returns a *suggestion* — it never writes the filter onto
  the watch itself. The client-side JS pre-fills form fields so the user
  reviews & saves.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import requests
from flask import Blueprint, jsonify, request
from flask_login import login_required
from loguru import logger


_API_URL = "https://api.anthropic.com/v1/messages"
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_LAST_CALL_BY_UUID: dict[str, float] = {}
_MIN_INTERVAL_SEC = 10


def _prompt(user_request: str, url: str, html_snippet: str) -> dict[str, Any]:
    system = (
        "You are a filter-generation assistant for changedetection.io, a web "
        "monitoring tool. Given a snippet of a page's HTML and a plain-English "
        "description of what the user wants to monitor, produce ONE JSON object "
        "with this exact shape:\n"
        '{ "include_filters": [<css or xpath strings>],'
        '  "subtractive_selectors": [<strings>],'
        '  "trigger_text": [<strings>],'
        '  "ignore_text": [<strings>],'
        '  "reasoning": "<one short sentence>" }\n'
        "Rules:\n"
        "- Prefer CSS selectors over XPath when both work.\n"
        "- Target only the narrowest element(s) that answer the user's request.\n"
        "- If the user wants a specific event (e.g. 'price drops below 100'), "
        "  populate trigger_text with a regex like /(?i)\\$?\\d{1,3}(\\.\\d+)?/. \n"
        "- If the user wants to ignore dynamic noise (timestamps, session IDs), "
        "  add ignore_text regexes.\n"
        "- Any list may be empty. NEVER return prose outside the JSON."
    )
    user = (
        f"PAGE URL: {url}\n\n"
        f"USER REQUEST: {user_request}\n\n"
        f"HTML (truncated):\n```\n{html_snippet}\n```\n\n"
        "Return the JSON object now."
    )
    return {"system": system, "user": user}


def _extract_json(text: str) -> dict | None:
    """Pull the first {...} block out of a model reply, tolerating chatter."""
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _resolve_api_key(datastore) -> str | None:
    key = (datastore.data["settings"]["application"].get("ai_filter_api_key") or "").strip()
    if key:
        return key
    return (os.getenv("ANTHROPIC_API_KEY") or "").strip() or None


def _fetch_watch_html(datastore, uuid: str, *, max_chars: int) -> str:
    """Best-effort read of the watch's latest snapshot as text, trimmed."""
    watch = datastore.data["watching"].get(uuid)
    if not watch:
        return ""
    try:
        latest_ts = watch.newest_history_key
        if not latest_ts:
            return ""
        snapshot_contents = watch.get_history_snapshot(timestamp=latest_ts)
        if isinstance(snapshot_contents, bytes):
            snapshot_contents = snapshot_contents.decode("utf-8", errors="ignore")
        return (snapshot_contents or "")[:max_chars]
    except Exception as e:
        logger.debug(f"ai_filter: failed to read snapshot for {uuid}: {e}")
        return ""


def construct_blueprint(datastore):
    blueprint = Blueprint("ai_filter", __name__)

    @blueprint.route("/<string:uuid>/suggest", methods=["POST"])
    @login_required
    def suggest(uuid):
        app_settings = datastore.data["settings"]["application"]

        if not app_settings.get("ai_filter_enabled"):
            return jsonify({"error": "AI filter assist is disabled in settings."}), 400

        api_key = _resolve_api_key(datastore)
        if not api_key:
            return jsonify({
                "error": "No API key configured. Set it in Settings → AI Assist, "
                         "or export ANTHROPIC_API_KEY.",
            }), 400

        if uuid not in datastore.data["watching"]:
            return jsonify({"error": f"Unknown watch {uuid}"}), 404

        # Simple per-watch rate limit.
        now = time.time()
        last = _LAST_CALL_BY_UUID.get(uuid, 0)
        if now - last < _MIN_INTERVAL_SEC:
            return jsonify({"error": "Please wait a few seconds before asking again."}), 429
        _LAST_CALL_BY_UUID[uuid] = now

        payload = request.get_json(silent=True) or {}
        user_request = (payload.get("request") or "").strip()
        if not user_request or len(user_request) > 500:
            return jsonify({"error": "Describe what you want to monitor (1–500 chars)."}), 400

        max_html_chars = int(os.getenv("AI_FILTER_MAX_HTML_CHARS", "20000"))
        html_snippet = _fetch_watch_html(datastore, uuid, max_chars=max_html_chars)
        watch_url = datastore.data["watching"][uuid].get("url", "")

        model = (app_settings.get("ai_filter_model") or _DEFAULT_MODEL).strip()
        prompt = _prompt(user_request, watch_url, html_snippet)

        body = {
            "model": model,
            "max_tokens": 600,
            "system": prompt["system"],
            "messages": [{"role": "user", "content": prompt["user"]}],
        }
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        try:
            r = requests.post(_API_URL, json=body, headers=headers, timeout=30)
        except requests.RequestException as e:
            logger.warning(f"ai_filter: network error: {e}")
            return jsonify({"error": f"Could not reach Anthropic API: {e}"}), 502

        if r.status_code != 200:
            logger.warning(f"ai_filter: anthropic returned {r.status_code}: {r.text[:300]}")
            return jsonify({
                "error": f"Anthropic API returned HTTP {r.status_code}. "
                         f"Check your API key and model name.",
            }), 502

        try:
            data = r.json()
            # Anthropic messages API: choices are under data['content'][0]['text']
            text_parts = [c.get("text", "") for c in data.get("content", []) if c.get("type") == "text"]
            raw_text = "\n".join(text_parts).strip()
        except Exception as e:
            logger.warning(f"ai_filter: could not parse anthropic response: {e}")
            return jsonify({"error": "Malformed response from Anthropic API."}), 502

        parsed = _extract_json(raw_text)
        if not parsed:
            return jsonify({
                "error": "The model did not return a valid JSON suggestion. "
                         "Try rephrasing or reducing the request.",
                "raw": raw_text[:2000],
            }), 502

        # Normalise: every list-field must be a list of strings.
        def _as_list(v):
            if v is None:
                return []
            if isinstance(v, list):
                return [str(x) for x in v if x]
            return [str(v)]

        suggestion = {
            "include_filters": _as_list(parsed.get("include_filters")),
            "subtractive_selectors": _as_list(parsed.get("subtractive_selectors")),
            "trigger_text": _as_list(parsed.get("trigger_text")),
            "ignore_text": _as_list(parsed.get("ignore_text")),
            "reasoning": str(parsed.get("reasoning") or "").strip()[:400],
            "model": model,
        }
        return jsonify(suggestion)

    return blueprint
