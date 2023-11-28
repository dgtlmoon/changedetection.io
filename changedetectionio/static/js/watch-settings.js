$(document).ready(function () {

    // Lazy Hide/Show elements mechanism
    $('[data-visible-for]').hide();
    $(':radio').on('keyup keypress blur change click', function (e){
        $('[data-visible-for]').hide();
        var n = $(this).attr('name') + "=" + $(this).val();
        if (n === 'fetch_backend=system') {
            n = "fetch_backend=" + default_system_fetch_backend;
        }
        $(`[data-visible-for~="${n}"]`).show();

    });
    $(':radio:checked').change();

    $('#notification-setting-reset-to-default').click(function (e) {
        $('#notification_title').val('');
        $('#notification_body').val('');
        $('#notification_format').val('System default');
        $('#notification_urls').val('');
        e.preventDefault();
    });
    $("#notification-token-toggle").click(function (e) {
        e.preventDefault();
        $('#notification-tokens-info').toggle();
    });
});
