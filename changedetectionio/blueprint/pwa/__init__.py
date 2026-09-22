"""Progressive Web App support - manifest, service worker, Android share target.

Both routes here are registered at the app ROOT (url_prefix=''), and that is load-bearing
rather than a style choice:

  - a manifest's scope defaults to its own directory, and the relative URLs it uses so that
    sub-path installs work resolve against the manifest's own URL. Served from anywhere but
    the root, the whole app would be scoped to that subdirectory,
  - a service worker can only control paths at or below its own URL, so from /pwa/sw.js its
    scope would be /pwa/ and it would control nothing - no WebAPK, and therefore no entry in
    the Android share sheet.

The third piece, the share target itself, lives in the watch list blueprint: the manifest
points share_target at the watch list so a shared link just prefills the quick-add form that
was already there. See service.pwa_preset_url().
"""

import os

from flask import Blueprint, make_response, render_template, request, send_from_directory, g

from changedetectionio.auth_decorator import login_optionally_required

from . import service

HERE = os.path.dirname(os.path.abspath(__file__))


def construct_blueprint():
    pwa_blueprint = Blueprint('pwa', __name__, template_folder="templates")

    @pwa_blueprint.app_template_global('pwa_https_mode')
    def pwa_https_mode():
        """Template-side gate for anything that invites a phone install.

        Registered app-wide (not just on this blueprint) so the Settings page - and a future
        welcome wizard - can ask the same question and get the same answer.
        """
        return service.https_mode(request.is_secure)

    @pwa_blueprint.route("/site.webmanifest", methods=['GET'])
    def site_webmanifest():
        """The PWA manifest.

        Not a static file, where it sat as a leftover of the 2022 favicon-generator import
        (3a8a41a3f), because: the scope problem above; Python's mimetypes has no entry for
        .webmanifest so send_from_directory hands it out as application/octet-stream; and
        the name has to vary per instance.
        """
        name, short_name = service.instance_names(
            forwarded_prefix=request.headers.get('X-Forwarded-Prefix'),
            script_root=request.script_root,
        )

        response = make_response(render_template(
            "manifest.json",
            name=name,
            short_name=short_name,
            # Deliberately not translated: this response is cached publicly and shared by
            # every visitor of the instance, so it can't carry one user's session locale.
            description=service.DESCRIPTION,
        ))
        response.headers['Content-Type'] = 'application/manifest+json'
        # Short TTL so a rename propagates, but long enough that the periodic re-fetch an
        # installed PWA performs isn't a per-navigation cost.
        response.headers['Cache-Control'] = 'public, max-age=3600'
        # Identical for every visitor of this instance, so let
        # PublicStaticAssetSessionInterface drop the "Vary: Cookie" that would otherwise key
        # it on the caller's session cookie.
        g.public_static_asset = True
        return response

    @pwa_blueprint.route("/sw.js", methods=['GET'])
    def service_worker():
        response = make_response(send_from_directory(os.path.join(HERE, "static"), path="sw.js"))
        response.headers['Content-Type'] = 'text/javascript'
        # The worker script itself must not be cached hard, or a fix to it can't be shipped:
        # browsers re-fetch it to detect updates and will honour a stale cache entry.
        response.headers['Cache-Control'] = 'no-cache, must-revalidate'
        g.public_static_asset = True
        return response

    @pwa_blueprint.route("/pwa/install-qrcode.svg", methods=['GET'])
    @login_optionally_required
    def install_qrcode():
        """QR code pointing at this instance, for installing the PWA on a phone.

        Getting the app onto a phone otherwise means typing a URL like
        https://example.com/my-instance/ on a phone keyboard, sub-path and all. That is the
        actual barrier to the share-sheet feature existing at all, so it is worth removing.

        Unlike the manifest and the worker, this one is NOT public - it is only rendered
        inside Settings, and it would tell an anonymous caller the instance's external
        address. The blueprint-wide exemption in check_authentication() deliberately lists
        endpoints rather than the whole blueprint, so adding a route here doesn't publish it.

        The path carries an explicit /pwa/ even though this blueprint is mounted at the
        root: only the manifest and the worker actually need to sit at the top level.

        SVG rather than PNG: a few hundred bytes, crisp at any size, no image library. Black
        on white regardless of theme - a QR needs its quiet zone and contrast, and an <img>
        can't inherit the page's dark mode anyway.
        """
        import io as _io

        import segno

        # request.url_root, NOT url_for(_external=True): url_for builds from the configured
        # SERVER_NAME, so behind a reverse proxy it emits the internal address and the QR
        # sends the phone somewhere it can't reach. url_root is scheme + host + sub-path
        # exactly as the browser asked for them.
        buffer = _io.BytesIO()
        segno.make(request.url_root, error='m').save(buffer, kind='svg', scale=4, border=2,
                                                     dark='#000000', light='#ffffff')

        response = make_response(buffer.getvalue())
        response.headers['Content-Type'] = 'image/svg+xml'
        response.headers['Cache-Control'] = 'no-store'
        return response

    return pwa_blueprint
