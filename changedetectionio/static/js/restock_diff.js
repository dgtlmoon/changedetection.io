$(document).ready(function () {
    // Initialize Visual Selector plugin
    let visualSelectorAPI = null;
    if ($('#selector-wrapper').length > 0) {
        visualSelectorAPI = $('#selector-wrapper').visualSelector({
            screenshotUrl: screenshot_url,
            visualSelectorDataUrl: watch_visual_selector_data_url,
            singleSelectorOnly: true,
            $includeFiltersElem: $('#restock_settings-price_change_custom_include_filters')
        });
    }
    // Bootstrap the visual selector when the tab is clicked
    $('#visualselector-tab').click(function () {
        if (visualSelectorAPI) {
            $('img#selector-background').off('load');
            visualSelectorAPI.bootstrap();
        }
    });
});

