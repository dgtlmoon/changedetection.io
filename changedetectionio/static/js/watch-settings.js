$(document).ready(function() {
    function toggle() {
        if ($('input[name="fetch_backend"]:checked').val() == 'html_webdriver') {
            if(playwright_enabled) {
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
        toggle();
    });
    toggle();

    $('#notification-setting-reset-to-default').click(function (e) {
        $('#notification_title').val('');
        $('#notification_body').val('');
        $('#notification_format').val('System default');
        $('#notification_urls').val('');
        e.preventDefault();
    });
});
