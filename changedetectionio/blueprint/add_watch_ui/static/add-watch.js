// Add Watch UI glue: fetch a live snapshot for the entered URL and drive the
// shared visual selector (window.initVisualSelector from visual-selector.js).

$(document).ready(() => {
    const $url = $('#url');
    const $go = $('#add-watch-go');
    const $emptyState = $('#add-watch-empty-state');
    const $spinner = $('#add-watch-spinner');
    const $error = $('#add-watch-error');
    const $wrapper = $('#selector-wrapper');
    const $xpathRow = $('#selector-current-xpath');
    const $byElement = $('#by-element-toggle');
    const $clear = $('#clear-selector');
    const $includeFilters = $('#include_filters');
    const $temporaryUuid = $('#temporary_uuid');

    // When the LLM intent box isn't available (LLM_FEATURES_DISABLED / not configured) the
    // template renders no "Select by element" checkbox - element selection is the only thing
    // this page can do, so it is on from the start and can't be turned off.
    const selectionAlwaysOn = $byElement.length === 0;
    const selectionEnabled = () => selectionAlwaysOn || $byElement.is(':checked');

    const vs = window.initVisualSelector({
        $canvas: $('#selector-canvas'),
        $includeFilters: $includeFilters,
        $background: $('#selector-background'),
        $xpathDisplay: $('#selector-current-xpath span'),
        $fetchingNotice: $('#add-watch-spinner .fetching-update-notice'),
        $wrapper: $wrapper,
        $clearButton: $clear,
        enableSelection: selectionAlwaysOn, // otherwise off until the user opts into "Select by element"
        processorIsImage: false,
        // The snapshot comes from the live browser-steps capture, so scale X by the page
        // CSS width (browser_width) like browser-steps.js - handles device-scale-factor != 1.
        scaleByBrowserWidth: true,
    });

    function showState(which) {
        // which: 'empty' | 'loading' | 'error' | 'ready'
        $emptyState.toggle(which === 'empty');
        $spinner.toggle(which === 'loading');
        $error.toggle(which === 'error');
        const ready = which === 'ready';
        $wrapper.toggle(ready);
        $xpathRow.toggle(ready && selectionEnabled());
        $clear.toggle(ready && selectionEnabled());
    }

    function fetchSnapshot() {
        const url = ($url.val() || '').trim();
        if (!url) {
            $url.focus();
            return;
        }

        showState('loading');
        // A previous parked snapshot is now stale; drop it until this fetch succeeds.
        $temporaryUuid.val('');

        $.ajax({
            url: add_watch_snapshot_url,
            // POST, never GET - this makes the server-side browser fetch a URL of our
            // choosing, so it must not be triggerable cross-origin. csrf.js adds the
            // X-CSRFToken header to every non-GET ajax call; the CSRF field on the form
            // is sent too so it works even if that handler hasn't run yet.
            method: 'POST',
            // Preview with the browser picked in the list - that same browser is what
            // gets saved on the watch, so what you see here is what it will check with.
            data: {
                url: url,
                fetch_backend: $('input[name="fetch_backend"]:checked').val() || '',
                csrf_token: $('#new-watch-form input[name="csrf_token"]').val() || '',
            },
            dataType: 'json',
        }).done((data) => {
            showState('ready');
            $temporaryUuid.val(data.temporary_uuid || '');
            vs.load({screenshotSrc: data.screenshot, xpathData: data.xpath_data});
        }).fail((xhr) => {
            const msg = (xhr && xhr.responseText) ? xhr.responseText : 'Could not fetch a preview for that URL.';
            $error.text(msg);
            showState('error');
        });
    }

    $go.on('click', fetchSnapshot);

    // Enter in the URL box should fetch a preview, not submit the whole form
    $url.on('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            fetchSnapshot();
        }
    });

    // "Select by element" toggles live hover/click element selection
    $byElement.on('change', function () {
        const on = $(this).is(':checked');
        vs.setSelectionEnabled(on);
        $xpathRow.toggle(on && $wrapper.is(':visible'));
        $clear.toggle(on && $wrapper.is(':visible'));
        if (!on) {
            $includeFilters.val('');
        }
    });

    showState('empty');
});
