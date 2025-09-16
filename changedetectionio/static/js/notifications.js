$(document).ready(function () {

    // Could be from 'watch' or system settings or other
    function getNotificationData() {
        data = {
            notification_body: $('textarea.notification-body').val(),
            notification_format: $('select.notification-format').val(),
            notification_title: $('input.notification-title').val(),
            notification_urls: $('textarea.notification-urls').val(),
            tags: $('#tags').val(),
            window_url: window.location.href,
        }
        return data
    }

    $('#add-email-helper').click(function (e) {
        e.preventDefault();
        email = prompt("Destination email");
        if (email) {
            var n = $(".notification-urls");
            var p = email_notification_prefix;
            $(n).val($.trim($(n).val()) + "\n" + email_notification_prefix + email);
        }
    });

    $('#notifications-minitabs').miniTabs({
        "Customise": "#notification-setup",
        "Preview": "#notification-preview",
    });

    $(document).on('click', '[data-target="#notification-preview"]', function (e) {
        var data = getNotificationData();
        $.ajax({
            type: "POST",
            url: notification_test_render_preview_url,
            data: data,
/*
            statusCode: {
                400: function (data) {
                    $("#notification-test-log>span").text(data.responseText);
                },
            }
*/
        }).done(function (data) {
            setPreview(data['result']);
        })

    });

    function setPreview(data) {
        const iframe = document.getElementById("notification-iframe");
        const isDark = document.documentElement.getAttribute('data-darkmode') === 'true';
        const isTextFormat = $('select.notification-format').val() === 'Text';

        $('#notification-preview-title-text').text(data['title']);

        iframe.srcdoc = `
        <html data-darkmode="${isDark}">
          <head>            
            <style>
                :root {
                  --color-white: #fff;
                  --color-grey-200: #333;
                  --color-grey-800: #e0e0e0;
                  --color-black: #000;
                  --color-dark-red: #a00;
                  --color-light-red: #dd0000;
                  --color-background: var(--color-grey-800);
                  --color-text: var(--color-grey-200);
                  }
                  
                    html[data-darkmode="true"] {
                      --color-background: var(--color-grey-200);
                      --color-text: var(--color-white);
                    }
                    body { /* no darkmode */
                        background-color: var(--color-background);
                        color: var(--color-text);
                        padding: 5px;
                    }
                    body.text-format {
                        font-family: monospace;
                        white-space: pre;
                        overflow-wrap: normal;
                        overflow-x: auto;
                    }
            </style>
          </head>
          <body class="${isTextFormat ? 'text-format' : ''}">${data['body']}</body>
        </html>`;
    }


    $('#send-test-notification').click(function (e) {
        e.preventDefault();

        var data = getNotificationData();

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
            $("#notification-test-log>span").text(data['status']);
        }).fail(function (jqXHR, textStatus, errorThrown) {
            // Handle connection refused or other errors
            if (textStatus === "error" && errorThrown === "") {
                console.error("Connection refused or server unreachable");
                $("#notification-test-log>span").text("Error: Connection refused or server is unreachable.");
            } else {
                console.error("Error:", textStatus, errorThrown);
                $("#notification-test-log>span").text("An error occurred: " + errorThrown);
            }
        }).always(function () {
            $('.notifications-wrapper .spinner').hide();
        })
    });


});

