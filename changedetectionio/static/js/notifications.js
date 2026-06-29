function checkDiscordHtmlWarning() {
    var urls = $('textarea.notification-urls').val() || '';
    var format = $('select.notification-format').val() || '';
    var isDiscord = /discord:\/\/|https:\/\/discord(?:app)?\.com\/api/i.test(urls);
    var isHtml = format === 'html' || format === 'htmlcolor';
    if (isDiscord && isHtml) {
        $('#discord-html-format-warning').show();
    } else {
        $('#discord-html-format-warning').hide();
    }
}

// Build a mailto-style Apprise URL from an email address using the configured preset.
// Supports a {TO} token anywhere in the preset; falls back to prefix+address.
function buildEmailUrl(email) {
    var p = (typeof email_notification_prefix !== 'undefined' && email_notification_prefix) ? email_notification_prefix : 'mailto://';
    if (p.indexOf('{TO}') !== -1) {
        return p.replace('{TO}', email);
    }
    return p + email;
}

// Turn a single Apprise URL into a friendly {icon, label} for the recipient chips.
function describeNotificationUrl(url) {
    var u = (url || '').trim();
    if (!u) return null;

    var isEmailPreset = false;
    if (typeof email_notification_prefix !== 'undefined' && email_notification_prefix) {
        var base = email_notification_prefix.indexOf('{TO}') !== -1
            ? email_notification_prefix.split('{TO}')[0]
            : email_notification_prefix;
        isEmailPreset = base && u.indexOf(base) === 0;
    }

    if (/^mailtos?:\/\//i.test(u) || isEmailPreset) {
        var addr = null;
        var toMatch = u.match(/[?&]to=([^&]+)/i);
        if (toMatch) {
            addr = decodeURIComponent(toMatch[1]);
        } else if (isEmailPreset) {
            var base2 = email_notification_prefix.indexOf('{TO}') !== -1
                ? email_notification_prefix.split('{TO}')[0]
                : email_notification_prefix;
            addr = u.substring(base2.length);
        } else {
            var m = u.match(/^mailtos?:\/\/([^?@\/]+@[^?\/]+)/i);
            if (m) addr = m[1];
        }
        return {type: 'email', icon: '✉', label: addr || u};
    }

    var scheme = (u.split('://')[0] || '').toLowerCase();
    var names = {
        discord: 'Discord', tgram: 'Telegram', telegram: 'Telegram', slack: 'Slack',
        tgrams: 'Telegram', gets: 'Webhook', posts: 'Webhook', get: 'Webhook', post: 'Webhook'
    };
    return {type: scheme || 'other', icon: '🔔', label: names[scheme] || (scheme || u)};
}

function notificationLines() {
    return ($('textarea.notification-urls').val() || '')
        .split('\n').map(function (s) { return s.trim(); }).filter(function (s) { return s.length; });
}

// Re-render the recipient chips from the textarea (the textarea stays the source of truth).
function renderNotificationRecipients() {
    var $container = $('#notification-recipients');
    if (!$container.length) return;
    var lines = notificationLines();
    $container.empty();
    if (!lines.length) { $container.hide(); return; }
    $container.show();

    lines.forEach(function (line) {
        var d = describeNotificationUrl(line);
        if (!d) return;
        var $chip = $('<span class="notification-chip"></span>').attr('data-url', line);
        $chip.append($('<span class="notification-chip-icon"></span>').text(d.icon));
        $chip.append($('<span class="notification-chip-label"></span>').text(d.label).attr('title', line));
        var $x = $('<a class="notification-chip-remove" title="Remove">✕</a>');
        $x.on('click', function (e) {
            e.preventDefault();
            removeNotificationLine(line);
        });
        $chip.append($x);
        $container.append($chip);
    });
}

function appendNotificationUrl(url) {
    var $ta = $('textarea.notification-urls');
    var cur = $.trim($ta.val() || '');
    $ta.val(cur ? cur + '\n' + url : url);
    $ta.trigger('input');
}

function removeNotificationLine(line) {
    var $ta = $('textarea.notification-urls');
    var kept = ($ta.val() || '').split('\n').filter(function (s) { return s.trim() !== line.trim(); });
    $ta.val(kept.join('\n'));
    $ta.trigger('input');
}

$(document).ready(function () {

    $('textarea.notification-urls, select.notification-format').on('change input', checkDiscordHtmlWarning);
    checkDiscordHtmlWarning();

    // Nothing to test against when there are no notification URLs - hide the button.
    function updateSendTestVisibility() {
        $('#send-test-notification').toggle(notificationLines().length > 0);
    }

    // Keep the friendly chips in sync whenever the raw URLs change (typed or programmatic).
    $('textarea.notification-urls').on('change input', function () {
        renderNotificationRecipients();
        updateSendTestVisibility();
    });
    renderNotificationRecipients();
    updateSendTestVisibility();

    // Email quick-add: the inline field is always visible when a preset is configured.
    function commitEmail() {
        var input = $('#add-email-input')[0];
        var email = $.trim($('#add-email-input').val());
        if (!email) return;
        // Use native email validation if available.
        if (input && input.checkValidity && !input.checkValidity()) {
            input.reportValidity();
            return;
        }
        appendNotificationUrl(buildEmailUrl(email));
        $('#add-email-input').val('').focus();
    }

    $('#add-email-go').click(function (e) {
        e.preventDefault();
        commitEmail();
    });

    $('#add-email-input').on('keydown', function (e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            commitEmail();
        }
    });

    $('#send-test-notification').click(function (e) {
        e.preventDefault();

        data = {
            notification_urls: $('textarea.notification-urls').val(),
            notification_title: $('input.notification-title').val(),
            notification_body: $('textarea.notification-body').val(),
            notification_format: $('select.notification-format').val(),
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

