$(document).ready(function () {
    function r() {
        $('ul#browser_steps select option:selected[value="Choose one"]').closest('li').css('opacity', 0.35);
    }

    $("ul#browser_steps select ").change(function () {
        $(this).closest('li').css('opacity', 1);
        r();
    });
    r();

    function toggle_ui() {
        var current = $('input[name=fetch_backend]:checked').val();
        if (current === 'html_webdriver') {
            $('#browser-steps-fieldlist').show();
        } else {
            $('#browser-steps-fieldlist').hide();
        }
    }

    $('input[name=fetch_backend]').change(function () {
        toggle_ui();
    });
    toggle_ui();
});