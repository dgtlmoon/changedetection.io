$(document).ready(function () {

    $('#add-email-helper').click(function (e) {
        e.preventDefault();
        email = prompt("Destination email");
        if (email) {
            var n = $(".notification-urls");
            var p = email_notification_prefix;
            $(n).val($.trim($(n).val()) + "\n" + email_notification_prefix + email);
        }
    });

    $('#send-test-notification').click(function (e) {
        e.preventDefault();

        var $btn = $(this);
        var $spinner = $('.notifications-wrapper .spinner');
        var $log = $('#notification-test-log');

        $spinner.fadeIn();
        $log.show();
        $log.find('span').text('Sending...');

        // Build data: if legacy notification_urls textarea exists (settings/group forms), include them
        var data = {
            window_url: window.location.href,
        };

        var $urlField = $('textarea.notification-urls');
        if ($urlField.length) {
            data.notification_urls = $urlField.val();
            data.notification_title = $('input.notification-title').val();
            data.notification_body = $('textarea.notification-body').val();
            data.notification_format = $('select.notification-format').val();
            data.tags = $('#tags').val();
        }

        $.ajax({
            type: "POST",
            url: notification_base_url,
            data: data,
            statusCode: {
                400: function (data) {
                    $log.find('span').text(data.responseText);
                },
            }
        }).done(function (data) {
            $log.find('span').text(data);
        }).fail(function (jqXHR, textStatus, errorThrown) {
            if (textStatus === "error" && errorThrown === "") {
                $log.find('span').text("Error: Connection refused or server is unreachable.");
            } else {
                $log.find('span').text("An error occurred: " + textStatus);
            }
        }).always(function () {
            $spinner.hide();
        });
    });
});
