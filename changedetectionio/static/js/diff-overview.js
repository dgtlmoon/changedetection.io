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

    const article = $('.highlightable-filter')[0];

    // We could also add the  'touchend' event for touch devices, but since
    // most iOS/Android browsers already show a dialog when you select
    // text (often with a Share option) we'll skip that
    article.addEventListener('mouseup', dragTextHandler, false);
    article.addEventListener('mousedown', clean, false);

    function clean(event) {
      $("#highlightSnippet").remove();
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

            // Find out how much (if any) user has scrolled
            var scrollTop = (window.pageYOffset !== undefined) ? window.pageYOffset : (document.documentElement || document.body.parentNode || document.body).scrollTop;

            // Get cursor position
            const posX = event.clientX;
            const posY = event.clientY + 20 + scrollTop;

            // Append HTML to the body, create the "Tweet Selection" dialog
            document.body.insertAdjacentHTML('beforeend', '<div id="highlightSnippet" style="position: absolute; top: ' + posY + 'px; left: ' + posX + 'px;"><div class="pure-form-message-inline" style="font-size: 70%">Ignore any change on any line which contains the selected text.</div><br><a data-mode="exact" href="javascript:void(0);" class="pure-button button-secondary button-xsmall">Ignore exact text</a>&nbsp;</div>');

            if (/\d/.test(window.getSelection().toString())) {
                // Offer regex replacement
                document.getElementById("highlightSnippet").insertAdjacentHTML('beforeend', '<a data-mode="digit-regex"  href="javascript:void(0);" class="pure-button button-secondary button-xsmall">Ignore text including number changes</a>');
            }

            $('#highlightSnippet a').bind('click', function (e) {
                if(!window.getSelection().toString().trim().length) {
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
                    $("#highlightSnippet").html(data)
                }).fail(function (data) {
                    console.log(data);
                    alert('There was an error communicating with the server.');
                });
            });

        }
    }

    $('#diff-form').on('submit', function (e) {
        if ($('select[name=from_version]').val() === $('select[name=to_version]').val()) {
            e.preventDefault();
            alert('Error - You are trying to compare the same version.');
        }
    });
});
