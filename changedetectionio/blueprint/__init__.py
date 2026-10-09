from flask import make_response


def plaintext_response(message, status):
    """
    Error response for a body that may contain caller-supplied text.

    Flask's make_response() defaults to Content-Type: text/html, so any user input echoed
    into an error body becomes reflected XSS. That is the failure behind
    GHSA-23mp-8222-96fr (/diff/<uuid>/download-patch), CVE-2026-27645 (/rss/watch/) and
    CVE-2026-29038 (/rss/tag/) - three instances of one pattern. Forcing text/plain means
    the browser will not parse the body as markup even if input does reach it.

    Prefer validating input over relying on this, but use it on error paths regardless:
    exception text routinely carries values nobody audited (selectors, timestamps,
    filesystem paths from snapshot reads).
    """
    response = make_response(message, status)
    response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    return response
