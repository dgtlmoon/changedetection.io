$(function () {
    var option_li=$('.fetch-backend-proxy input[type="radio"]').parent();
    $(option_li).append('<div class="proxy-status"></div>');

    function set_proxy_check_status(proxy_key, status) {
        $(".proxy-status", option_li).append('<div class="proxy-status"></div>');
    }

    $('#check-all-proxies').click(function (e) {
        e.preventDefault()

        // look at the return object, set the status
        set_proxy_check_status("europe-germany", "OK")
    });

});

