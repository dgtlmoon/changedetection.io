$(document).ready(function () {
    // Load it when the #screenshot tab is in use, so we dont give a slow experience when waiting for the text diff to load
    window.addEventListener('hashchange', function (e) {
        toggle(location.hash);
    }, false);

    toggle(location.hash);

    function toggle(hash_name) {
        if (hash_name === '#screenshot') {
            $("img#screenshot-img").attr('src', screenshot_url);
            $("#settings").hide();
        } else if (hash_name === '#error-screenshot') {
            $("img#error-screenshot-img").attr('src', error_screenshot_url);
            $("#settings").hide();
        }


        else {
            $("#settings").show();
        }
    }
});
