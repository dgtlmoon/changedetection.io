function setupDiffNavigation() {
    var $fromSelect = $('#diff-from-version');
    var $toSelect = $('#diff-to-version');
    var $fromSelected = $fromSelect.find('option:selected');
    var $toSelected = $toSelect.find('option:selected');

    if ($fromSelected.length && $toSelected.length) {
        // Find the previous pair (move both back one position)
        var $prevFrom = $fromSelected.prev();
        var $prevTo = $toSelected.prev();

        // Find the next pair (move both forward one position)
        var $nextFrom = $fromSelected.next();
        var $nextTo = $toSelected.next();

        // Build URL with current diff preferences
        var currentParams = new URLSearchParams(window.location.search);

        // Previous button: only show if both can move back
        if ($prevFrom.length && $prevTo.length) {
            currentParams.set('from_version', $prevFrom.val());
            currentParams.set('to_version', $prevTo.val());
            $('#btn-previous').attr('href', '?' + currentParams.toString());
        } else {
            $('#btn-previous').remove();
        }

        // Next button: only show if both can move forward
        if ($nextFrom.length && $nextTo.length) {
            currentParams.set('from_version', $nextFrom.val());
            currentParams.set('to_version', $nextTo.val());
            $('#btn-next').attr('href', '?' + currentParams.toString());
        } else {
            $('#btn-next').remove();
        }
    }

    // Keyboard navigation
    window.addEventListener('keydown', function (event) {
        // Don't trigger if user is typing in an input field
        if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA' || event.target.tagName === 'SELECT') {
            return;
        }

        var $fromSelected = $fromSelect.find('option:selected');
        var $toSelected = $toSelect.find('option:selected');

        if ($fromSelected.length && $toSelected.length) {
            if (event.key === 'ArrowLeft') {
                var $prevFrom = $fromSelected.prev();
                var $prevTo = $toSelected.prev();
                if ($prevFrom.length && $prevTo.length) {
                    var prevHref = $('#btn-previous').attr('href');
                    if (prevHref) {
                        event.preventDefault();
                        window.location.href = prevHref;
                    }
                }
            } else if (event.key === 'ArrowRight') {
                var $nextFrom = $fromSelected.next();
                var $nextTo = $toSelected.next();
                if ($nextFrom.length && $nextTo.length) {
                    var nextHref = $('#btn-next').attr('href');
                    if (nextHref) {
                        event.preventDefault();
                        window.location.href = nextHref;
                    }
                }
            }
        }
    }, false);
}

// The seven diff options collapse behind the 'Filters' button so the sticky bar
// stays one toolbar row. Wired up here rather than purely in CSS: until this
// runs the fieldset is inline and the toggle hidden, so with scripting off the
// options are still reachable and still submit with the form.
function setupDiffFilters() {
    var header = document.getElementById('diff-header');
    var toggle = document.getElementById('diff-filters-toggle');
    var panel = document.getElementById('diff-style');
    if (!header || !toggle || !panel) {
        return;
    }

    header.classList.add('diff-filters-js');

    function isOpen() {
        return header.classList.contains('diff-filters-open');
    }

    // The panel is position: fixed - #diff-header's overflow: auto would clip an
    // absolutely positioned one - so it has to be parked under the button by
    // hand, and kept inside the viewport on a narrow screen.
    function place() {
        var button = toggle.getBoundingClientRect();
        var available = document.documentElement.clientWidth - panel.offsetWidth - 8;
        panel.style.top = (button.bottom + 4) + 'px';
        panel.style.left = Math.max(8, Math.min(button.left, available)) + 'px';
    }

    function open() {
        header.classList.add('diff-filters-open');
        toggle.setAttribute('aria-expanded', 'true');
        place();
    }

    function close(restoreFocus) {
        if (!isOpen()) {
            return;
        }
        header.classList.remove('diff-filters-open');
        toggle.setAttribute('aria-expanded', 'false');
        if (restoreFocus) {
            toggle.focus();
        }
    }

    toggle.addEventListener('click', function (event) {
        event.preventDefault();
        if (isOpen()) {
            close(false);
        } else {
            open();
        }
    });

    document.addEventListener('click', function (event) {
        if (isOpen() && !panel.contains(event.target) && !toggle.contains(event.target)) {
            close(false);
        }
    });

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
            close(true);
        }
    });

    // The bar is sticky directly under the top menu, so the button keeps its
    // viewport position as the page scrolls and only a resize can move it out
    // from under the panel. A tab switch hides #settings, and the panel with it,
    // so drop the open state rather than leave aria-expanded lying.
    window.addEventListener('resize', function () {
        if (isOpen()) {
            place();
        }
    });
    window.addEventListener('hashchange', function () {
        close(false);
    });
}

$(document).ready(function () {
    $('.needs-localtime').each(function () {
        for (var option of this.options) {
            var dateObject = new Date(option.value * 1000);
            var formattedDate = dateObject.toLocaleString(undefined, {dateStyle: "full", timeStyle: "medium"});
            // Preserve any existing text in the label (like "(Previous)" or "(Current)")
            var existingText = option.text.replace(option.value, '').trim();
            option.label = existingText ? formattedDate + ' ' + existingText : formattedDate;
        }
    });

    // Setup keyboard navigation for diff versions
    if ($('#diff-from-version').length && $('#diff-to-version').length) {
        setupDiffNavigation();
    }

    setupDiffFilters();

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
        article.addEventListener('mousedown', clean, false);
    }

    // Because they might 'mouse up' outside the article but on the page
    const d_page = $(".difference-page")[0]
    if (d_page ) {
        d_page.addEventListener('mouseup', dragTextHandler, false);
    }


    $('#highlightSnippetActions a').bind('click', function (e) {
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
            alert("'Ignore' Filters for this watch were updated.")
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
