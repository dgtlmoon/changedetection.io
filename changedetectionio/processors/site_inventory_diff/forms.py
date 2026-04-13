"""
Form for the site_inventory_diff processor.

Follows the same pattern as restock_diff: a ``processor_settings_form``
subclassing the main text/json diff form, with an ``extra_tab_content()``
label and an ``extra_form_content()`` returning a Jinja2 template string.

Field names are persisted verbatim into ``site_inventory_diff.json`` by the
same plumbing that handles ``processor_config_restock_diff`` —
see ``extract_processor_config_from_form_data()`` in
``/changedetectionio/processors/__init__.py``.
"""

from __future__ import annotations

from flask_babel import lazy_gettext as _l
from wtforms import (
    BooleanField,
    FloatField,
    IntegerField,
    StringField,
    validators,
)
from wtforms.fields.choices import RadioField
from wtforms.fields.form import FormField
from wtforms.form import Form

from changedetectionio.forms import processor_text_json_diff_form


def _validate_optional_regex(form, field):
    """Compile the pattern (if any) so bad regex fails form validation early."""
    import re

    if field.data:
        try:
            re.compile(field.data)
        except re.error as exc:
            raise validators.ValidationError(
                _l("Invalid regular expression: %(err)s", err=str(exc))
            )


class InventorySettingsForm(Form):
    source_type = RadioField(
        label=_l("Source type"),
        choices=[
            ("auto", _l("Auto-detect (recommended)")),
            ("sitemap", _l("Sitemap XML (or sitemap index)")),
            ("html", _l("HTML listing page")),
            ("crawl", _l("Bounded crawl (beta)")),
        ],
        default="auto",
    )

    css_scope = StringField(
        _l("CSS scope (HTML mode only)"),
        [validators.Optional()],
        render_kw={
            "placeholder": ".post-list, article",
            "autocomplete": "off",
        },
    )

    same_origin_only = BooleanField(
        _l("Same origin only"),
        default=True,
    )

    strip_query_strings = BooleanField(
        _l("Strip query strings"),
        default=True,
    )

    strip_tracking_params_always = BooleanField(
        _l("Always strip tracking parameters (utm_*, gclid, fbclid, …)"),
        default=True,
    )

    follow_sitemap_index = BooleanField(
        _l("Follow sitemap indexes (recurse into child sitemaps)"),
        default=True,
    )

    include_regex = StringField(
        _l("Include regex (only keep URLs matching this)"),
        [validators.Optional(), _validate_optional_regex],
        render_kw={"placeholder": r"^https?://example\.com/blog/"},
    )

    exclude_regex = StringField(
        _l("Exclude regex (drop URLs matching this)"),
        [validators.Optional(), _validate_optional_regex],
        render_kw={"placeholder": r"/tag/|/author/"},
    )

    # --- Crawl mode (v2) -------------------------------------------------

    crawl_max_pages = IntegerField(
        _l("Crawl: max pages"),
        [validators.Optional(), validators.NumberRange(min=1, max=10_000)],
        default=100,
    )
    crawl_max_depth = IntegerField(
        _l("Crawl: max depth"),
        [validators.Optional(), validators.NumberRange(min=0, max=10)],
        default=2,
    )
    crawl_delay_seconds = FloatField(
        _l("Crawl: delay between requests (seconds)"),
        [validators.Optional(), validators.NumberRange(min=0, max=60)],
        default=1.0,
    )
    crawl_time_budget_seconds = FloatField(
        _l("Crawl: total time budget (seconds)"),
        [validators.Optional(), validators.NumberRange(min=1, max=1800)],
        default=60.0,
    )
    crawl_respect_robots_txt = BooleanField(
        _l("Crawl: respect robots.txt"),
        default=True,
    )


class processor_settings_form(processor_text_json_diff_form):
    processor_config_site_inventory_diff = FormField(InventorySettingsForm)

    def extra_tab_content(self):
        return _l("Site Inventory")

    def extra_form_content(self):
        # Jinja fragment — rendered by blueprint/ui/edit.py when this
        # processor_settings_form class is selected for a watch.
        return """
        {% from '_helpers.html' import render_field, render_checkbox_field %}
        <fieldset id="site-inventory-fieldset">
          <div class="pure-control-group">
            <p class="pure-form-message-inline">
              {{ _('Detect when pages are added to or removed from a site. The snapshot is a sorted list of canonical URLs; the diff engine does the rest.') }}
            </p>
            <fieldset class="pure-group inline-radio">
              {{ render_field(form.processor_config_site_inventory_diff.source_type) }}
              <span class="pure-form-message-inline">
                {{ _('"Auto" sniffs the response as sitemap or HTML. Pick "Bounded crawl" only when the site has no sitemap and no good listing page.') }}
              </span>
            </fieldset>

            <fieldset class="pure-group">
              {{ render_field(form.processor_config_site_inventory_diff.css_scope, class='m-d') }}
              <span class="pure-form-message-inline">
                {{ _('Only applied when source type is "HTML listing page". Restrict anchor extraction to descendants of this CSS selector.') }}
              </span>
            </fieldset>

            <fieldset class="pure-group">
              {{ render_checkbox_field(form.processor_config_site_inventory_diff.same_origin_only) }}
              <span class="pure-form-message-inline">{{ _('Drop links that point off-site. Recommended.') }}</span>
            </fieldset>

            <fieldset class="pure-group">
              {{ render_checkbox_field(form.processor_config_site_inventory_diff.strip_query_strings) }}
              <span class="pure-form-message-inline">{{ _('Treat ?page=1 / ?sort=... as the same page. Safer default; turn off if you really do care about query-parameter-driven pages.') }}</span>
            </fieldset>

            <fieldset class="pure-group">
              {{ render_checkbox_field(form.processor_config_site_inventory_diff.strip_tracking_params_always) }}
              <span class="pure-form-message-inline">{{ _('Even when query strings are kept, drop tracking params like utm_*, gclid, fbclid, ref.') }}</span>
            </fieldset>

            <fieldset class="pure-group">
              {{ render_checkbox_field(form.processor_config_site_inventory_diff.follow_sitemap_index) }}
              <span class="pure-form-message-inline">{{ _('When a sitemap points to other sitemaps, follow them (up to 50 children).') }}</span>
            </fieldset>

            <fieldset class="pure-group">
              {{ render_field(form.processor_config_site_inventory_diff.include_regex, class='m-d') }}
            </fieldset>
            <fieldset class="pure-group">
              {{ render_field(form.processor_config_site_inventory_diff.exclude_regex, class='m-d') }}
            </fieldset>

            <details style="margin-top: 1rem;">
              <summary><strong>{{ _('Bounded crawl settings (only used when source type is "Bounded crawl")') }}</strong></summary>
              <div style="padding-top: 0.75rem;">
                <fieldset class="pure-group">
                  {{ render_field(form.processor_config_site_inventory_diff.crawl_max_pages) }}
                </fieldset>
                <fieldset class="pure-group">
                  {{ render_field(form.processor_config_site_inventory_diff.crawl_max_depth) }}
                </fieldset>
                <fieldset class="pure-group">
                  {{ render_field(form.processor_config_site_inventory_diff.crawl_delay_seconds) }}
                </fieldset>
                <fieldset class="pure-group">
                  {{ render_field(form.processor_config_site_inventory_diff.crawl_time_budget_seconds) }}
                </fieldset>
                <fieldset class="pure-group">
                  {{ render_checkbox_field(form.processor_config_site_inventory_diff.crawl_respect_robots_txt) }}
                  <span class="pure-form-message-inline">
                    {{ _('Strongly recommended. Disable only on sites you own or have explicit permission to crawl.') }}
                  </span>
                </fieldset>
              </div>
            </details>
          </div>
        </fieldset>
        """
