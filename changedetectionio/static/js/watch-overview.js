$(function () {
    // Remove unviewed status when normally clicked
    $('.diff-link').click(function () {
        $(this).closest('.unviewed').removeClass('unviewed');
    });

    $('td[data-timestamp]').each(function () {
        $(this).prop('title', new Intl.DateTimeFormat(undefined,
            {
                dateStyle: 'full',
                timeStyle: 'long'
            }).format($(this).data('timestamp') * 1000));
    })

    $("#checkbox-assign-tag").click(function (e) {
        $('#op_extradata').val(prompt("Enter a tag name"));
    });

    $('.with-share-link > *').click(function () {
        $("#copied-clipboard").remove();

        var range = document.createRange();
        var n = $("#share-link")[0];
        range.selectNode(n);
        window.getSelection().removeAllRanges();
        window.getSelection().addRange(range);
        document.execCommand("copy");
        window.getSelection().removeAllRanges();

        $('.with-share-link').append('<span style="font-size: 80%; color: #fff;" id="copied-clipboard">Copied to clipboard</span>');
        $("#copied-clipboard").fadeOut(2500, function () {
            $(this).remove();
        });
    });

    $(".watch-table tr").click(function (event) {
        var tagName = event.target.tagName.toLowerCase();
        if (tagName === 'tr' || tagName === 'td') {
            var x = $('input[type=checkbox]', this);
            if (x) {
                $(x).click();
            }
        }
    });

    // checkboxes - check all
    $("#check-all").click(function (e) {
        $('input[type=checkbox]').not(this).prop('checked', this.checked);
    });

    const time_check_step_size_seconds=1;

    // checkboxes - show/hide buttons
    $("input[type=checkbox]").click(function (e) {
        if ($('input[type=checkbox]:checked').length) {
            $('#checkbox-operations').slideDown();
        } else {
            $('#checkbox-operations').slideUp();
        }
    });

    setInterval(function () {
        // Background ETA completion for 'checking now'
        $(".watch-table .checking-now .last-checked").each(function () {
            const eta_complete = parseFloat($(this).data('eta_complete'));
            const fetch_duration = parseInt($(this).data('fetchduration'));

            if (eta_complete + 2 > nowtimeserver && fetch_duration > 3) {
                const remaining_seconds = Math.abs(eta_complete) - nowtimeserver - 1;

                let r = Math.round((1.0 - (remaining_seconds / fetch_duration)) * 100);
                if (r < 10) {
                    r = 10;
                }
                if (r >= 90) {
                    r = 100;
                }
                $(this).css('background-size', `${r}% 100%`);
            } else {
                // Snap to full complete
                $(this).css('background-size', `100% 100%`);
            }
        });

        nowtimeserver = nowtimeserver + time_check_step_size_seconds;
    }, time_check_step_size_seconds * 1000);
});

