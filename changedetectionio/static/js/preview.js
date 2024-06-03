function redirect_to_version(version) {
    var currentUrl = window.location.href;
    var baseUrl = currentUrl.split('?')[0]; // Base URL without query parameters
    var anchor = '';

    // Check if there is an anchor
    if (baseUrl.indexOf('#') !== -1) {
        anchor = baseUrl.substring(baseUrl.indexOf('#'));
        baseUrl = baseUrl.substring(0, baseUrl.indexOf('#'));
    }
    window.location.href = baseUrl + '?version=' + version + anchor;
}

document.addEventListener('keydown', function (event) {
    var selectElement = document.getElementById('preview-version');
    if (selectElement) {
        var selectedOption = selectElement.querySelector('option:checked');
        if (selectedOption) {
            if (event.key === 'ArrowLeft') {
                if (selectedOption.previousElementSibling) {
                    redirect_to_version(selectedOption.previousElementSibling.value);
                }
            } else if (event.key === 'ArrowRight') {
                if (selectedOption.nextElementSibling) {
                    redirect_to_version(selectedOption.nextElementSibling.value);
                }
            }
        }
    }
});


document.getElementById('preview-version').addEventListener('change', function () {
    redirect_to_version(this.value);
});

var selectElement = document.getElementById('preview-version');
if (selectElement) {
    var selectedOption = selectElement.querySelector('option:checked');
    if (selectedOption) {
        if (selectedOption.previousElementSibling) {
            document.getElementById('btn-previous').href = "?version=" + selectedOption.previousElementSibling.value;
        } else {
            document.getElementById('btn-previous').remove()
        }
        if (selectedOption.nextElementSibling) {
            document.getElementById('btn-next').href = "?version=" + selectedOption.nextElementSibling.value;
        } else {
            document.getElementById('btn-next').remove()
        }

    }
}
