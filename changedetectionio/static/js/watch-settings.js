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

function getTimeInTimezone(timezone) {
    const now = new Date();
    const options = {
        timeZone: timezone,
        weekday: 'long',
        year: 'numeric',
        hour12: false,
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    };

    const formatter = new Intl.DateTimeFormat('en-US', options);
    return formatter.format(now);
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

    window.setInterval(function () {
        if ($("#time_schedule_limit-timezone").val().length) {
            document.getElementById('local-time-in-tz').textContent =
                getTimeInTimezone($("#time_schedule_limit-timezone").val());
        } else {
            // So maybe use what is in the placeholder (which will be the default settings)
            document.getElementById('local-time-in-tz').textContent =
                getTimeInTimezone($("#time_schedule_limit-timezone").attr('placeholder'));
        }
    }, 500);

    $('#time_schedule_limit-saturday, #time_schedule_limit-sunday').addClass("weekend-day")

    $(document).on('click', '[data-template].set-schedule', function() {
    // Get the value of the 'data-template' attribute

        switch ($(this).attr('data-template')) {
            case 'business-hours':
                $('table:not(.weekend-day) input[type="time"]').val('09:00')
                $('table:not(.weekend-day) select[id*="-duration-hours"]').val('8');
                $('table:not(.weekend-day) select[id*="-duration-minutes"]').val('0');
                $('input[id*="-enabled"]').prop('checked', true);
                $('.weekend-day input[id*="-enabled"]').prop('checked', false);
                break;
            case 'weekend':
                $('.weekend-day input[type="time"][id$="start-time"]').val('00:00')
                $('.weekend-day select[id*="-duration-hours"]').val('24');
                $('.weekend-day select[id*="-duration-minutes"]').val('0');
                $('input[id*="-enabled"]').prop('checked', false);
                $('.weekend-day input[id*="-enabled"]').prop('checked', true);
                break;
            case 'reset':
                $('.day-schedule input[type="time"]').val('00:00')
                $('.day-schedule select[id*="-duration-hours"]').val('24');
                $('.day-schedule select[id*="-duration-minutes"]').val('0');
                $('.day-schedule input[id*="-enabled"]').prop('checked', true);
                break;
            case 'once-per-day':
                $('.day-schedule input[type="time"]').val('00:00')
                $('.day-schedule select[id*="-duration-hours"]').val('24');
                $('.day-schedule select[id*="-duration-minutes"]').val('0');
                $('.day-schedule input[id*="-enabled"]').prop('checked', true);
                break;
        }
    });
    
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

    toggleOpacity('#time_between_check_use_default', '#time_between_check, #time-between-check-schedule', false);
    toggleOpacity('#time_schedule_limit-enabled', '#day-wrapper', true)

    const vh = Math.max(document.documentElement.clientHeight || 0, window.innerHeight || 0);
    $("#text-preview-inner").css('max-height', (vh-300)+"px");
    $("#text-preview-before-inner").css('max-height', (vh-300)+"px");

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

