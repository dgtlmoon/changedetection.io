$(document).ready(function () {

    // Lazy Hide/Show elements mechanism
    $('[data-visible-for]').hide();
    $(':radio').on('keyup keypress blur change click', function (e) {
        $('[data-visible-for]').hide();
        $('.advanced-options').hide();
        var n = $(this).attr('name') + "=" + $(this).val();
        if (n === 'fetch_backend=system') {
            n = "fetch_backend=" + default_system_fetch_backend;
        }
        $(`[data-visible-for~="${n}"]`).show();

    });
    $(':radio:checked').change();


    // Show advanced
    $('.show-advanced').click(function (e) {
        $(this).closest('.tab-pane-inner').find('.advanced-options').toggle();
    });
});