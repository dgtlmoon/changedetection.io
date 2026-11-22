#!/usr/bin/env python3
"""
POST /diff/<uuid>/llm-summary is CSRF-protected, and the page that calls it must actually
send the token.

The start call became a POST in #4467 because it spends tokens and marks the watch viewed,
so it must not be reachable from a cross-site GET. That protection immediately broke the
feature with "400 The CSRF token is missing", for a load-order reason:

  1. diff.html has an inline <script> that registers a jQuery ready handler while the
     document is still parsing, and that handler calls llmSummary.fetch() straight away.
  2. csrf.js is loaded with `defer`, so it runs AFTER parsing.
  3. It used to wrap $.ajaxSetup in $(document).ready(). jQuery runs ready callbacks in
     registration order, so the inline handler's POST fired before the token was configured.

$.ajaxSetup needs no DOM, so it now runs at script-execution time. Deferred scripts all
execute before DOMContentLoaded, which puts the setup in place before any ready handler runs.
"""

import os

CSRF_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'static', 'js', 'csrf.js')


def test_csrf_setup_is_not_deferred_to_document_ready():
    """A ready handler registered by an inline block always wins the race against this file."""
    src = open(CSRF_JS).read()
    # Strip // comments - the explanation above the call names the very thing we forbid
    code = '\n'.join(line.split('//')[0] for line in src.splitlines())

    assert '$.ajaxSetup(' in code
    before = code[:code.index('$.ajaxSetup(')]

    assert 'document).ready' not in before and '$(function' not in before, (
        "$.ajaxSetup must run at script-execution time, not inside a ready handler - "
        "inline page scripts register their ready callbacks first and would POST untokened"
    )


def test_llm_summary_post_requires_a_csrf_token(client, live_server):
    """Keep the protection itself - the fix is to send the token, not to drop the guard."""
    res = client.post('/diff/does-not-matter/llm-summary')
    assert res.status_code in (400, 404), (
        f"expected a CSRF rejection (or 404 before it), got {res.status_code}"
    )
