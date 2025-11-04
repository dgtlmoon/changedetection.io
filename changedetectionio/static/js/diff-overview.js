$(document).ready(function () {
    $('.needs-localtime').each(function () {
        for (var option of this.options) {
            var dateObject = new Date(option.value * 1000);
            option.label = dateObject.toLocaleString(undefined, {dateStyle: "full", timeStyle: "medium"});
        }
    });

    // Load it when the #screenshot tab is in use, so we dont give a slow experience when waiting for the text diff to load
    window.addEventListener('hashchange', function (e) {
        toggle(location.hash);
    }, false);

    toggle(location.hash);

    function toggle(hash_name) {
        if (hash_name === '#screenshot') {
            $("img#screenshot-img").attr('src', screenshot_url);
            $("#settings").hide();
        } else if (hash_name === '#error-screenshot') {
            $("img#error-screenshot-img").attr('src', error_screenshot_url);
            $("#settings").hide();
        } else if (hash_name === '#extract') {
            $("#settings").hide();
        } else {
            $("#settings").show();
        }
    }

    const article = $('#difference')[0];

    // We could also add the  'touchend' event for touch devices, but since
    // most iOS/Android browsers already show a dialog when you select
    // text (often with a Share option) we'll skip that
    if (article) {
        article.addEventListener('mouseup', dragTextHandler, false);
        article.addEventListener('mousedown', clean, false);
    }


    $('#highlightSnippetActions button').bind('click', function (e) {
        if (!window.getSelection().toString().trim().length) {
            alert('Oops no text selected!');
            return;
        }

        $.ajax({
            type: "POST",
            url: highlight_submit_ignore_url,
            data: {'mode': $(this).data('mode'), 'selection': window.getSelection().toString()},
            statusCode: {
                400: function () {
                    // More than likely the CSRF token was lost when the server restarted
                    alert("There was a problem processing the request, please reload the page.");
                }
            }
        }).done(function (data) {
            // @todo some feedback
            $("#highlightSnippet").html(data);
            clean();
        }).fail(function (data) {
            console.log(data);
            alert('There was an error communicating with the server.');
        })
    });

    function clean(event) {
        $('#bottom-horizontal-offscreen').hide();
    }

    // Listen for Escape key press
    window.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
            clean();
        }
    }, false);

    function dragTextHandler(event) {
        console.log('mouseupped');

        // Check if any text was selected
        if (window.getSelection().toString().length > 0) {
            $('#bottom-horizontal-offscreen').show();
        } else {
            clean();
        }
    }

    $('#diff-form').on('submit', function (e) {
        if ($('select[name=from_version]').val() === $('select[name=to_version]').val()) {
            e.preventDefault();
            alert('Error - You are trying to compare the same version.');
        }
    });

    // Auto-submit form on change of any input elements (checkboxes, radio buttons, dropdowns)
    $('#diff-form').on('change', 'input[type="checkbox"], input[type="radio"], select', function (e) {
        // Check if we're trying to compare the same version before submitting
        if ($('select[name=from_version]').val() !== $('select[name=to_version]').val()) {
            $('#diff-form').submit();
        }
    });
});
