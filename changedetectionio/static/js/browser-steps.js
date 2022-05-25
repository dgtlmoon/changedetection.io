$(document).ready(function () {
    function r() {
        $('ul#browser_steps select option:selected[value="Choose one"]').closest('li').css('opacity', 0.35);
    }

    $("ul#browser_steps select ").change(function () {
        $(this).closest('li').css('opacity', 1);
        r();
    });
    r();

});