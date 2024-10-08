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


function request_textpreview_update() {
    if (!$('body').hasClass('preview-text-enabled')) {
        console.error("Preview text was requested but body tag was not setup")
        return
    }

    const data = {};
    $('textarea:visible, input:visible').each(function () {
        const $element = $(this); // Cache the jQuery object for the current element
        const name = $element.attr('name'); // Get the name attribute of the element
        data[name] = $element.is(':checkbox') ? ($element.is(':checked') ? $element.val() : false) : $element.val();
    });
    $('#text-preview-spinner').show();
    $.abortiveSingularAjax({
        type: "POST",
        url: preview_text_edit_filters_url,
        data: data,
        namespace: 'watchEdit'
    }).done(function (data) {
        $('#text-preview-spinner').fadeOut();
        $('#filters-and-triggers #text-preview-before-inner').text(data['before_filter']);
        $('#filters-and-triggers #text-preview-inner')
            .text(data['after_filter'])
            .highlightLines([
                {
                    'color': '#ee0000',
                    'lines': data['trigger_line_numbers']
                }
            ]);
    }).fail(function (error) {
        $('#text-preview-spinner').fadeOut();
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
    $("#text-preview-before-inner").css('max-height', (vh-300)+"px");

    // Realtime preview of 'Filters & Text' setup
    var debounced_request_textpreview_update = request_textpreview_update.debounce(100);

    $("#activate-text-preview").click(function (e) {
        $('body').toggleClass('preview-text-enabled')
        request_textpreview_update();

        const method = $('body').hasClass('preview-text-enabled') ? 'on' : 'off';
        $("#text-preview-refresh")[method]('click', debounced_request_textpreview_update);
        $('textarea:visible')[method]('keyup blur', debounced_request_textpreview_update);
        $('input:visible')[method]('keyup blur change', debounced_request_textpreview_update);
        $("#filters-and-triggers-tab")[method]('click', debounced_request_textpreview_update);
    });
    $('.minitabs-wrapper').miniTabs({
        "Content after filters": "#text-preview-inner",
        "Content raw/before filters": "#text-preview-before-inner"
    });
});

