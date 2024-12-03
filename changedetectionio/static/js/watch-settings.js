
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

    $('body').toggleClass('spinner-active', 1);

    $.abortiveSingularAjax({
        type: "POST",
        url: preview_text_edit_filters_url,
        data: data,
        namespace: 'watchEdit'
    }).done(function (data) {
        console.debug(data['duration'])
        $('#filters-and-triggers #text-preview-before-inner').text(data['before_filter']);
        $('#filters-and-triggers #text-preview-inner')
            .text(data['after_filter'])
            .highlightLines([
                {
                    'color': '#ee0000',
                    'lines': data['trigger_line_numbers']
                },
                {
                    'color': '#757575',
                    'lines': data['ignore_line_numbers']
                }
            ])
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

    toggleOpacity('#time_between_check_use_default', '#time-check-widget-wrapper, #time-between-check-schedule', false);


    const vh = Math.max(document.documentElement.clientHeight || 0, window.innerHeight || 0);
    $("#text-preview-inner").css('max-height', (vh - 300) + "px");
    $("#text-preview-before-inner").css('max-height', (vh - 300) + "px");

    $("#activate-text-preview").click(function (e) {
        $('body').toggleClass('preview-text-enabled')
        request_textpreview_update();
        const method = $('body').hasClass('preview-text-enabled') ? 'on' : 'off';
        $('#filters-and-triggers textarea')[method]('blur', request_textpreview_update.throttle(1000));
        $('#filters-and-triggers input')[method]('change', request_textpreview_update.throttle(1000));
        $("#filters-and-triggers-tab")[method]('click', request_textpreview_update.throttle(1000));
    });
    $('.minitabs-wrapper').miniTabs({
        "Content after filters": "#text-preview-inner",
        "Content raw/before filters": "#text-preview-before-inner"
    });
});

