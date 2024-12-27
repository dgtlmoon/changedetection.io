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

$(document).ready(function () {

    let exceedsLimit = false;
    const warning_text = $("#timespan-warning")
    const timezone_text_widget = $("input[id*='time_schedule_limit-timezone']")

    toggleVisibility('#time_schedule_limit-enabled, #requests-time_schedule_limit-enabled', '#schedule-day-limits-wrapper', true)

    setInterval(() => {
        let success = true;
        try {
            // Show the current local time according to either placeholder or entered TZ name
            if (timezone_text_widget.val().length) {
                $('#local-time-in-tz').text(getTimeInTimezone(timezone_text_widget.val()));
            } else {
                // So maybe use what is in the placeholder (which will be the default settings)
                $('#local-time-in-tz').text(getTimeInTimezone(timezone_text_widget.attr('placeholder')));
            }
        } catch (error) {
            success = false;
            $('#local-time-in-tz').text("");
            console.error(timezone_text_widget.val())
        }

        $(timezone_text_widget).toggleClass('error', !success);

    }, 500);

    $('#schedule-day-limits-wrapper').on('change click blur', 'input, checkbox, select', function() {

        let allOk = true;

        // Controls setting the warning that the time could overlap into the next day
        $("li.day-schedule").each(function () {
            const $schedule = $(this);
            const $checkbox = $schedule.find("input[type='checkbox']");

            if ($checkbox.is(":checked")) {
                const timeValue = $schedule.find("input[type='time']").val();
                const durationHours = parseInt($schedule.find("select[name*='-duration-hours']").val(), 10) || 0;
                const durationMinutes = parseInt($schedule.find("select[name*='-duration-minutes']").val(), 10) || 0;

                if (timeValue) {
                    const [startHours, startMinutes] = timeValue.split(":").map(Number);
                    const totalMinutes = (startHours * 60 + startMinutes) + (durationHours * 60 + durationMinutes);

                    exceedsLimit = totalMinutes > 1440
                    if (exceedsLimit) {
                        allOk = false
                    }
                    // Set the row/day-of-week highlight
                    $schedule.toggleClass("warning", exceedsLimit);
                }
            } else {
                $schedule.toggleClass("warning", false);
            }
        });

        warning_text.toggle(!allOk)
    });

    $('table[id*="time_schedule_limit-saturday"], table[id*="time_schedule_limit-sunday"]').addClass("weekend-day")

    // Presets [weekend] [business hours] etc
    $(document).on('click', '[data-template].set-schedule', function () {
        // Get the value of the 'data-template' attribute
        switch ($(this).attr('data-template')) {
            case 'business-hours':
                $('.day-schedule table:not(.weekend-day) input[type="time"]').val('09:00')
                $('.day-schedule table:not(.weekend-day) select[id*="-duration-hours"]').val('8');
                $('.day-schedule table:not(.weekend-day) select[id*="-duration-minutes"]').val('0');
                $('.day-schedule input[id*="-enabled"]').prop('checked', true);
                $('.day-schedule .weekend-day input[id*="-enabled"]').prop('checked', false);
                break;
            case 'weekend':
                $('.day-schedule .weekend-day input[type="time"][id$="start-time"]').val('00:00')
                $('.day-schedule .weekend-day select[id*="-duration-hours"]').val('24');
                $('.day-schedule .weekend-day select[id*="-duration-minutes"]').val('0');
                $('.day-schedule input[id*="-enabled"]').prop('checked', false);
                $('.day-schedule .weekend-day input[id*="-enabled"]').prop('checked', true);
                break;
            case 'reset':

                $('.day-schedule input[type="time"]').val('00:00')
                $('.day-schedule select[id*="-duration-hours"]').val('24');
                $('.day-schedule select[id*="-duration-minutes"]').val('0');
                $('.day-schedule input[id*="-enabled"]').prop('checked', true);
                break;
        }
    });
});
