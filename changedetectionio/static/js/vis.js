$(document).ready(function () {

    // Lazy Hide/Show elements mechanism
    $('[data-visible-for]').hide();
    function show_related_elem(e) {
        var n = $(e).attr('name') + "=" + $(e).val();
        if (n === 'fetch_backend=system') {
            n = "fetch_backend=" + default_system_fetch_backend;
        }
        // A group (or plugin) decides the fetch method for this watch, show the fields for that one
        if ($(e).attr('name') === 'fetch_backend' && typeof decided_fetch_backend !== 'undefined' && decided_fetch_backend) {
            n = "fetch_backend=" + decided_fetch_backend;
        }
        $(`[data-visible-for~="${n}"]`).show();
    }
    $(':radio').on('keyup keypress blur change click', function (e) {
        $(`[data-visible-for]`).hide();
        $('.advanced-options').hide();
        show_related_elem(this);
    });

    $(':radio:checked').each(function (e) {
       show_related_elem(this);
    })


    // Show advanced
    $('.show-advanced').click(function (e) {
        $(this).closest('.tab-pane-inner').find('.advanced-options').each(function (e) {
            $(this).toggle();
        })
    });
});