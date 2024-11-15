function redirectToVersion(version) {
    var currentUrl = window.location.href.split('?')[0]; // Base URL without query parameters
    var anchor = '';

    // Check if there is an anchor
    if (currentUrl.indexOf('#') !== -1) {
        anchor = currentUrl.substring(currentUrl.indexOf('#'));
        currentUrl = currentUrl.substring(0, currentUrl.indexOf('#'));
    }

    window.location.href = currentUrl + '?version=' + version + anchor;
}

function setupDateWidget() {
    $(document).on('keydown', function (event) {
        var $selectElement = $('#preview-version');
        var $selectedOption = $selectElement.find('option:selected');

        if ($selectedOption.length) {
            if (event.key === 'ArrowLeft' && $selectedOption.prev().length) {
                redirectToVersion($selectedOption.prev().val());
            } else if (event.key === 'ArrowRight' && $selectedOption.next().length) {
                redirectToVersion($selectedOption.next().val());
            }
        }
    });

    $('#preview-version').on('change', function () {
        redirectToVersion($(this).val());
    });

    var $selectedOption = $('#preview-version option:selected');

    if ($selectedOption.length) {
        var $prevOption = $selectedOption.prev();
        var $nextOption = $selectedOption.next();

        if ($prevOption.length) {
            $('#btn-previous').attr('href', '?version=' + $prevOption.val());
        } else {
            $('#btn-previous').remove();
        }

        if ($nextOption.length) {
            $('#btn-next').attr('href', '?version=' + $nextOption.val());
        } else {
            $('#btn-next').remove();
        }
    }
}

$(document).ready(function () {
    if ($('#preview-version').length) {
        setupDateWidget();
    }

    $('#diff-col > pre').highlightLines([
        {
            'color': '#ee0000',
            'lines': triggered_line_numbers
        }
    ]);
});
