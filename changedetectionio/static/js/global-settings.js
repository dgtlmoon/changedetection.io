$(document).ready(function () {
    // Secret fields (the LLM API key) render with readonly set, because Chrome ignores
    // autocomplete="off" on type=password and will happily drop the saved site password in.
    // That is destructive rather than merely annoying: the field renders blank so that
    // saving it untouched PRESERVES the stored key, so anything prefilled silently replaces
    // a working key on the next Save, with no copy kept anywhere to restore from.
    //
    // readonly rather than disabled - a disabled input is never submitted, so the key could
    // never be set at all. Unlocked on focus as well as click so keyboard tabbing works.
    $('[data-unlock-on-interact]').on('focus click', function () {
        $(this).removeAttr('readonly');
    });

    $("#api-key").hover(
        function () {
            $("#api-key-copy").html('copy').fadeIn();
        },
        function () {
            $("#api-key-copy").hide();
        }
    ).click(function (e) {
        $("#api-key-copy").html('copied');
        var range = document.createRange();
        var n = $("#api-key")[0];
        range.selectNode(n);
        window.getSelection().removeAllRanges();
        window.getSelection().addRange(range);
        document.execCommand("copy");
        window.getSelection().removeAllRanges();

    });

    $(".toggle-show").click(function (e) {
        e.preventDefault();
        let target = $(this).data('target');
        $(target).toggle();
    });

    // Handle processor radio button changes - update body class
    $('input[name="processor"]').on('change', function() {
        var selectedProcessor = $(this).val();

        // Remove any existing processor-* classes from body
        $('body').removeClass(function(index, className) {
            return (className.match(/\bprocessor-\S+/g) || []).join(' ');
        });

        // Add the new processor class
        $('body').addClass('processor-' + selectedProcessor);
    });

    // Time zone config related
    $(".local-time").each(function (e) {
        $(this).text(new Date($(this).data("utc")).toLocaleString());
    })

    const timezoneInput = $('#application-scheduler_timezone_default');
    if(timezoneInput.length) {
        const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        if (!timezoneInput.val().trim()) {
            timezoneInput.val(timezone);
            timezoneInput.after('<div class="timezone-message">The timezone was set from your browser, <strong>be sure to press save!</strong></div>');
        }
    }

});

