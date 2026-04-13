"""
Public marketing pages for the onChange by Sairo deployment at change.sairo.app.

This blueprint provides the *only* pages on the site that are intended to be
crawled and indexed:

* ``/welcome``              — landing page with hero, feature grid, CTA
* ``/features``             — detailed feature breakdown (including site inventory)
* ``/about``                — project story + attribution to changedetection.io
* ``/privacy``              — brief privacy posture for a self-hosted tool
* ``/accessibility``        — WCAG 2.2 AA accessibility statement
* ``/accessibility/vpat``   — VPAT 2.5Rev WCAG 2.2 conformance report
* ``/robots.txt``           — dynamic; allow marketing paths, disallow app paths
* ``/sitemap.xml``          — dynamic; lists the public marketing URLs

Every response sets ``page_public=True`` so ``base.html`` emits
``robots: index,follow`` — every OTHER page on the site inherits the default
``noindex,nofollow`` from ``base.html``.

Self-hosted operators who want zero public pages can simply front the app
with a reverse proxy that blocks ``/welcome``, ``/features``, ``/about``,
``/privacy``, ``/sitemap.xml``, or disable the blueprint entirely in
``flask_app.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from flask import Blueprint, Response, render_template, request, url_for


# Paths that should always be Disallow-ed in robots.txt regardless of login
# state. These are clearly "app" surfaces; exposing them to bots wastes crawl
# budget and can leak UUIDs via diff/preview URLs.
_ROBOTS_DISALLOWS: tuple[str, ...] = (
    "/edit/",
    "/diff/",
    "/preview/",
    "/static/screenshot/",
    "/static/visual_selector_data/",
    "/static/favicon/",
    "/api/",
    "/login",  # password form; no SEO value
    "/logout",
    "/settings",
    "/imports",
    "/backups",
    "/tags",
    "/site-inventory/watch/",  # per-watch CSV export
    "/rss",
    "/check_proxy",
    "/browser-steps",
    "/conditions",
    "/watch-templates",
    "/ui/",
)

# Public marketing paths that go into sitemap.xml. Must resolve via url_for
# to avoid drift if the route names change.
_SITEMAP_ENDPOINTS: tuple[str, ...] = (
    "marketing.landing",
    "marketing.features",
    "marketing.about",
    "marketing.privacy",
    "marketing.accessibility",
    "marketing.vpat",
)


def construct_blueprint() -> Blueprint:
    bp = Blueprint(
        "marketing",
        __name__,
        template_folder="templates",
    )

    def _render_public(template_name: str, **ctx):
        """Shortcut: render a marketing template with ``page_public=True``
        so the base template opts into index,follow + full OG/Twitter meta.
        """
        return render_template(template_name, page_public=True, **ctx)

    @bp.route("/welcome", methods=["GET"], endpoint="landing")
    def landing():
        return _render_public(
            "marketing/landing.html",
            seo_title=(
                "onChange by Sairo — detect any change on any web page"
            ),
            seo_description=(
                "Watch websites for changes: text, prices, restocks, sitemaps, "
                "whole-site URL inventories. Self-hosted, open source, "
                "built on changedetection.io."
            ),
            seo_keywords=(
                "website change detection, sitemap monitoring, price tracking, "
                "restock alerts, self-hosted monitoring, open source, "
                "onChange, Sairo, changedetection.io fork"
            ),
            seo_canonical=url_for("marketing.landing", _external=True),
        )

    @bp.route("/features", methods=["GET"], endpoint="features")
    def features():
        return _render_public(
            "marketing/features.html",
            seo_title="Features — onChange by Sairo",
            seo_description=(
                "Explore every monitoring mode: full-text diff, visual filter, "
                "restock & price, full-site URL inventory with bounded crawl, "
                "AppRise notifications, digest emails, AI-assisted filters."
            ),
            seo_canonical=url_for("marketing.features", _external=True),
        )

    @bp.route("/about", methods=["GET"], endpoint="about")
    def about():
        return _render_public(
            "marketing/about.html",
            seo_title="About — onChange by Sairo",
            seo_description=(
                "onChange by Sairo is a friendly fork of the open-source "
                "changedetection.io project, with an updated brand, a new "
                "site-inventory processor, and accessibility polish. "
                "Apache 2.0 licensed."
            ),
            seo_canonical=url_for("marketing.about", _external=True),
        )

    @bp.route("/privacy", methods=["GET"], endpoint="privacy")
    def privacy():
        return _render_public(
            "marketing/privacy.html",
            seo_title="Privacy — onChange by Sairo",
            seo_description=(
                "How onChange by Sairo handles data on a self-hosted "
                "deployment: what's collected, what's shared, what never "
                "leaves your server."
            ),
            seo_canonical=url_for("marketing.privacy", _external=True),
        )

    @bp.route("/accessibility", methods=["GET"], endpoint="accessibility")
    def accessibility():
        return _render_public(
            "marketing/accessibility.html",
            seo_title="Accessibility statement — onChange by Sairo",
            seo_description=(
                "Accessibility statement for onChange by Sairo. We target "
                "WCAG 2.2 Level AA and publish a per-criterion VPAT 2.5Rev "
                "conformance report covering the full Level A and AA set."
            ),
            seo_keywords=(
                "accessibility, WCAG 2.2, WCAG 2.2 AA, VPAT, Section 508, "
                "EN 301 549, screen reader, keyboard navigation, "
                "onChange, Sairo"
            ),
            seo_canonical=url_for("marketing.accessibility", _external=True),
        )

    @bp.route(
        "/accessibility/vpat", methods=["GET"], endpoint="vpat"
    )
    def vpat():
        return _render_public(
            "marketing/vpat.html",
            seo_title=(
                "VPAT 2.5Rev — WCAG 2.2 conformance — onChange by Sairo"
            ),
            seo_description=(
                "Voluntary Product Accessibility Template (VPAT 2.5Rev) "
                "for onChange by Sairo, reporting per-criterion conformance "
                "with WCAG 2.2 Levels A and AA."
            ),
            seo_keywords=(
                "VPAT, VPAT 2.5, VPAT 2.5Rev, WCAG 2.2, WCAG 2.2 AA, "
                "Section 508, EN 301 549, accessibility conformance"
            ),
            seo_canonical=url_for("marketing.vpat", _external=True),
        )

    # -----------------------------------------------------------------
    # robots.txt — dynamic so we can reflect the current host and
    # sitemap URL without hard-coding.
    # -----------------------------------------------------------------
    @bp.route("/robots.txt", methods=["GET"], endpoint="robots_txt")
    def robots_txt():
        lines = ["User-agent: *"]
        for path in _ROBOTS_DISALLOWS:
            lines.append(f"Disallow: {path}")
        # Explicitly allow static brand assets that the social-scrapers need.
        lines.append("Allow: /static/images/og-image.svg")
        lines.append("Allow: /static/favicons/")
        lines.append("")
        lines.append(
            f"Sitemap: {url_for('marketing.sitemap_xml', _external=True)}"
        )
        body = "\n".join(lines) + "\n"
        return Response(body, mimetype="text/plain")

    # -----------------------------------------------------------------
    # sitemap.xml — lists the public marketing pages. Intentionally small:
    # every other page is behind auth or contains user UUIDs.
    # -----------------------------------------------------------------
    @bp.route("/sitemap.xml", methods=["GET"], endpoint="sitemap_xml")
    def sitemap_xml():
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        entries: list[tuple[str, str, str]] = []
        priorities = {
            "marketing.landing": ("1.0", "weekly"),
            "marketing.features": ("0.9", "monthly"),
            "marketing.about": ("0.6", "monthly"),
            "marketing.privacy": ("0.3", "yearly"),
            "marketing.accessibility": ("0.5", "yearly"),
            "marketing.vpat": ("0.4", "yearly"),
        }
        for ep in _SITEMAP_ENDPOINTS:
            prio, freq = priorities.get(ep, ("0.5", "monthly"))
            entries.append((url_for(ep, _external=True), prio, freq))

        xml = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for loc, prio, freq in entries:
            xml.append("  <url>")
            xml.append(f"    <loc>{loc}</loc>")
            xml.append(f"    <lastmod>{now}</lastmod>")
            xml.append(f"    <changefreq>{freq}</changefreq>")
            xml.append(f"    <priority>{prio}</priority>")
            xml.append("  </url>")
        xml.append("</urlset>")
        return Response("\n".join(xml), mimetype="application/xml")

    return bp
