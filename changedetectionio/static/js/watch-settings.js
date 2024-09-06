function toggleOpacity(checkboxSelector, fieldSelector, inverted) {
    const checkbox = document.querySelector(checkboxSelector);
    const fields = document.querySelectorAll(fieldSelector);
    function updateOpacity() {
        const opacityValue = !checkbox.checked ? (inverted ? 0.6 : 1) : (inverted ? 1 : 0.6);
        fields.forEach(field => {
            field.style.opacity = opacityValue;
        });
    }
    // Initial setup
    updateOpacity();
    checkbox.addEventListener('change', updateOpacity);
}

function request_textpreview_update() {
    const data = {};
    $('textarea:visible, input:visible').each(function () {
        const $element = $(this); // Cache the jQuery object for the current element
        const name = $element.attr('name'); // Get the name attribute of the element
        data[name] = $element.is(':checkbox') ? ($element.is(':checked') ? $element.val() : undefined) : $element.val();
    });

    $.ajax({
        type: "POST",
        url: preview_text_edit_filters_url,
        data: data
    }).done(function (data) {
        $('#filters-and-triggers #text-preview-inner').text(data);
    }).fail(function (data) {
        console.log(data);
        $('#filters-and-triggers #text-preview-inner').text('There was an error communicating with the server.');
    })
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

    toggleOpacity('#time_between_check_use_default', '#time_between_check', false);

    const vh = Math.max(document.documentElement.clientHeight || 0, window.innerHeight || 0);
    $("#text-preview-inner").css('max-height', (vh-300)+"px");

    $("#activate-text-preview").click(function (e) {
        $(this).fadeOut();
        $('body').toggleClass('preview-text-enabled')

        request_textpreview_update();
        $("#text-preview-refresh").click(function (e) {
            request_textpreview_update();
        });
        $('textarea:visible, input:visible').on('keyup keypress blur change click', function (e) {
            request_textpreview_update();
        });

    });

});

