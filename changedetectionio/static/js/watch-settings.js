function toggleOpacity(checkboxSelector, fieldSelector) {
    const checkbox = document.querySelector(checkboxSelector);
    const fields = document.querySelectorAll(fieldSelector);
    function updateOpacity() {
        const opacityValue = checkbox.checked ? 0.6 : 1;
        fields.forEach(field => {
            field.style.opacity = opacityValue;
        });
    }
    // Initial setup
    updateOpacity();
    checkbox.addEventListener('change', updateOpacity);
}

$(document).ready(function () {
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

    toggleOpacity('#time_between_check_use_default', '#time_between_check');
});

