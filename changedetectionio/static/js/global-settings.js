$(document).ready(function () {
    function toggle() {
        if ($('input[name="application-fetch_backend"]:checked').val() != 'html_requests') {
            $('#requests-override-options').hide();
            $('#webdriver-override-options').show();
        } else {
            $('#requests-override-options').show();
            $('#webdriver-override-options').hide();
        }
    }

    $('input[name="application-fetch_backend"]').click(function (e) {
        toggle();
    });
    toggle();

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
});

