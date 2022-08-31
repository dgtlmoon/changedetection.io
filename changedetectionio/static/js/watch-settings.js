$(document).ready(function () {
    function toggle_fetch_backend() {
        if ($('input[name="fetch_backend"]:checked').val() == 'html_webdriver') {
            if (playwright_enabled) {
                // playwright supports headers, so hide everything else
                // See #664
                $('#requests-override-options #request-method').hide();
                $('#requests-override-options #request-body').hide();

                // @todo connect this one up
                $('#ignore-status-codes-option').hide();
            } else {
                // selenium/webdriver doesnt support anything afaik, hide it all
                $('#requests-override-options').hide();
            }
            $('#webdriver-override-options').show();
        } else {
            $('#requests-override-options').show();
            $('#requests-override-options *:hidden').show();
            $('#webdriver-override-options').hide();
        }
    }

    $('input[name="fetch_backend"]').click(function (e) {
        toggle_fetch_backend();
    });
    toggle_fetch_backend();

    function toggle_default_notifications() {
        var n=$('#notification_urls, #notification_title, #notification_body, #notification_format');
        if ($('#notification_use_default').is(':checked')) {
            $(n).each(function (e) {
                $(this).attr('readonly', true).css('opacity',0.5);
            });
        } else {
            $(n).each(function (e) {
                $(this).attr('readonly', false).css('opacity',1);
            });
        }
    }

    $('#notification_use_default').click(function (e) {
        toggle_default_notifications();
    });
    toggle_default_notifications();
});
