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

        data = {
            notification_body: $('#notification_body').val(),
            notification_format: $('#notification_format').val(),
            notification_title: $('#notification_title').val(),
            notification_urls: $('.notification-urls').val(),
            tags: $('#tags').val(),
            window_url: window.location.href,
        }

        $('.notifications-wrapper .spinner').fadeIn();
        $('#notification-test-log').show();
        $.ajax({
            type: "POST",
            url: notification_base_url,
            data: data,
            statusCode: {
                400: function (data) {
                    $("#notification-test-log>span").text(data.responseText);
                },
            }
        }).done(function (data) {
            $("#notification-test-log>span").text(data);
        }).fail(function (jqXHR, textStatus, errorThrown) {
            // Handle connection refused or other errors
            if (textStatus === "error" && errorThrown === "") {
                console.error("Connection refused or server unreachable");
                $("#notification-test-log>span").text("Error: Connection refused or server is unreachable.");
            } else {
                console.error("Error:", textStatus, errorThrown);
                $("#notification-test-log>span").text("An error occurred: " + textStatus);
            }
        }).always(function () {
            $('.notifications-wrapper .spinner').hide();
        })
    });
});

