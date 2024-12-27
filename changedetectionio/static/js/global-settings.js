$(document).ready(function () {
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

    // Time zone config related
    $(".local-time").each(function (e) {
        $(this).text(new Date($(this).data("utc")).toLocaleString());
    })

    const timezoneInput = $('#application-timezone');
    if(timezoneInput.length) {
        const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        if (!timezoneInput.val().trim()) {
            timezoneInput.val(timezone);
            timezoneInput.after('<div class="timezone-message">The timezone was set from your browser, <strong>be sure to press save!</strong></div>');
        }
    }

});

