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
    const $processorPreview = $('#processor-add-watch-ui-preview-text');

    // Per-processor previews from the last snapshot ({processor_name: "line to show"}).
    let processorPreviews = {};

    function renderProcessorPreview() {
        const selected = $('input[name="processor"]:checked').val();
        const text = selected ? processorPreviews[selected] : null;
        $processorPreview.text(text || '').toggle(!!text);
    }

    const vs = window.initVisualSelector({
        $canvas: $('#selector-canvas'),
        $includeFilters: $includeFilters,
        $background: $('#selector-background'),
        $xpathDisplay: $('#selector-current-xpath span'),
        $fetchingNotice: $('#add-watch-spinner .fetching-update-notice'),
        $wrapper: $wrapper,
        $clearButton: $clear,
        enableSelection: false, // off until the user opts into "Select by element"
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
        $xpathRow.toggle(ready && $byElement.is(':checked'));
        $clear.toggle(ready && $byElement.is(':checked'));
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
        processorPreviews = {};
        renderProcessorPreview();

        // Preview with whichever interactive browser the user picked (defaults to the checked one).
        const browser = $('input[name="fetch_backend"]:checked').val() || '';

        $.ajax({
            url: add_watch_snapshot_url,
            data: {url: url, browser: browser},
            dataType: 'json',
        }).done((data) => {
            showState('ready');
            $temporaryUuid.val(data.temporary_uuid || '');
            processorPreviews = data.processor_previews || {};
            renderProcessorPreview();
            vs.load({screenshotSrc: data.screenshot, xpathData: data.xpath_data});
        }).fail((xhr) => {
            const msg = (xhr && xhr.responseText) ? xhr.responseText : 'Could not fetch a preview for that URL.';
            $error.text(msg);
            showState('error');
        });
    }

    // Swap the preview line when the processor selection changes (no re-fetch needed).
    $(document).on('change', 'input[name="processor"]', renderProcessorPreview);

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
