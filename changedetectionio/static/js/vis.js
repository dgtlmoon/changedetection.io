$(document).ready(function () {

    // Lazy Hide/Show elements mechanism
    $('[data-visible-for]').hide();
    function show_related_elem(e) {
        var name = $(e).attr('name');
        var val = $(e).val();
        var n = name + "=" + val;

        // Resolve browser_profile select → underlying fetch_backend class name
        // browserProfileFetcherMap is injected by the page as {machine_name: 'playwright', ...}
        if (name && name.endsWith('browser_profile') && typeof browserProfileFetcherMap !== 'undefined') {
            var fetcherClass = val === 'system'
                ? (typeof default_system_fetch_backend !== 'undefined' ? default_system_fetch_backend : null)
                : browserProfileFetcherMap[val];
            if (fetcherClass) {
                n = 'fetch_backend=' + fetcherClass;
            }
        } else if (n === 'fetch_backend=system') {
            n = "fetch_backend=" + default_system_fetch_backend;
        }
        $(`[data-visible-for~="${n}"]`).show();
    }

    $('select, :radio').on('change', function (e) {
        $(`[data-visible-for]`).hide();
        $('.advanced-options').hide();
        show_related_elem(this);
    });
    // Retain original click/keyup handling for radio buttons
    $(':radio').on('keyup keypress blur click', function (e) {
        $(`[data-visible-for]`).hide();
        $('.advanced-options').hide();
        show_related_elem(this);
    });

    $(':radio:checked, select').each(function (e) {
       show_related_elem(this);
    });


    // Show advanced
    $('.show-advanced').click(function (e) {
        $(this).closest('.tab-pane-inner').find('.advanced-options').each(function (e) {
            $(this).toggle();
        })
    });
});
