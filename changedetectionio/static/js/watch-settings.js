function toggleOpacity(checkboxSelector, fieldSelector, inverted) {
    const checkbox = document.querySelector(checkboxSelector);
    const fields = document.querySelectorAll(fieldSelector);
    function updateOpacity() {
        const opacityValue = !checkbox.checked ? (inverted ? 0.6 : 1) : (inverted ? 1 : 0.6);
        fields.forEach(field => {
            field.style.opacity = opacityValue;
        });
    }
    // Initial setup
    updateOpacity();
    checkbox.addEventListener('change', updateOpacity);
}

(function($) {
    // Object to store ongoing requests by namespace
    const requests = {};

    $.abortiveSingularAjax = function(options) {
        const namespace = options.namespace || 'default';

        // Abort the current request in this namespace if it's still ongoing
        if (requests[namespace]) {
            requests[namespace].abort();
        }

        // Start a new AJAX request and store its reference in the correct namespace
        requests[namespace] = $.ajax(options);

        // Return the current request in case it's needed
        return requests[namespace];
    };
})(jQuery);

function request_textpreview_update() {
    if (!$('body').hasClass('preview-text-enabled')) {
        return
    }

    const data = {};
    $('textarea:visible, input:visible').each(function () {
        const $element = $(this); // Cache the jQuery object for the current element
        const name = $element.attr('name'); // Get the name attribute of the element
        data[name] = $element.is(':checkbox') ? ($element.is(':checked') ? $element.val() : undefined) : $element.val();
    });

    $.abortiveSingularAjax({
        type: "POST",
        url: preview_text_edit_filters_url,
        data: data,
        namespace: 'watchEdit'
    }).done(function (data) {
        $('#filters-and-triggers #text-preview-inner').text(data);
    }).fail(function (error) {
        if (error.statusText === 'abort') {
            console.log('Request was aborted due to a new request being fired.');
        } else {
            $('#filters-and-triggers #text-preview-inner').text('There was an error communicating with the server.');
        }
    })
}

$(document).ready(function () {
    $('#notification-setting-reset-to-default').click(function (e) {
        $('#notification_title').val('');
        $('#notification_body').val('');
        $('#notification_format').val('System default');
        $('#notification_urls').val('');
        e.preventDefault();
    });
    $("#notification-token-toggle").click(function (e) {
        e.preventDefault();
        $('#notification-tokens-info').toggle();
    });

    toggleOpacity('#time_between_check_use_default', '#time_between_check', false);

    const vh = Math.max(document.documentElement.clientHeight || 0, window.innerHeight || 0);
    $("#text-preview-inner").css('max-height', (vh-300)+"px");
    var debounced_request_textpreview_update = request_textpreview_update.debounce(100);

    $("#activate-text-preview").click(function (e) {
        $(this).fadeOut();
        $('body').toggleClass('preview-text-enabled')

        request_textpreview_update();

        $("#text-preview-refresh").click(function (e) {
            request_textpreview_update();
        });
        $('textarea:visible').on('keyup blur', debounced_request_textpreview_update);
        $('input:visible').on('keyup blur change', debounced_request_textpreview_update);
        $("#filters-and-triggers-tab").on('click', debounced_request_textpreview_update);
    });

});

