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

    // Function to check and bootstrap visual selector based on hash
    function checkAndBootstrapVisualSelector() {
        if (visualSelectorAPI) {
            if (window.location.hash && window.location.hash.includes('visualselector')) {
                $('img#selector-background').off('load');
                visualSelectorAPI.bootstrap();
            } else {
                // Shutdown when navigating away from visualselector
                visualSelectorAPI.shutdown();
            }
        }
    }

    // Bootstrap the visual selector when the tab is clicked
    $('#visualselector-tab').click(function () {
        if (visualSelectorAPI) {
            $('img#selector-background').off('load');
            visualSelectorAPI.bootstrap();
        }
    });

    // Check on page load if hash contains 'visualselector'
    checkAndBootstrapVisualSelector();

    // Listen for hash changes (when anchor changes)
    $(window).on('hashchange', function() {
        checkAndBootstrapVisualSelector();
    });
});

