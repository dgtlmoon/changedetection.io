$(document).ready(function() {
    function toggle() {
        if ($('input[name="fetch_backend"]:checked').val() != 'html_requests') {
            $('#requests-override-options').hide();
        } else {
            $('#requests-override-options').show();
        }
    }
    $('input[name="fetch_backend"]').click(function (e) {
        toggle();
    });
    toggle();

});
