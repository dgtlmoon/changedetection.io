// Previous / Next step both version selects one position back or forward and
// rebuild the href from the current diff options; the arrow keys do the same
// thing. Recomputed at press time rather than cached, because changing either
// select submits the form and re-renders them.
function diffStepHref(direction) {
    var $from = $('#diff-from-version option:selected')[direction]();
    var $to = $('#diff-to-version option:selected')[direction]();
    if (!$from.length || !$to.length) {
        return null;
    }
    var params = new URLSearchParams(window.location.search);
    params.set('from_version', $from.val());
    params.set('to_version', $to.val());
    return '?' + params.toString();
}

function setupDiffNavigation() {
    var BUTTONS = {prev: '#btn-previous', next: '#btn-next'};

    if ($('#diff-from-version option:selected').length && $('#diff-to-version option:selected').length) {
        $.each(BUTTONS, function (direction, selector) {
            var href = diffStepHref(direction);
            // Nothing to step to that way: drop the button rather than leave a
            // dead one on the bar.
            if (href) {
                $(selector).attr('href', href);
            } else {
                $(selector).remove();
            }
        });
    }

    $(window).on('keydown', function (event) {
        // Not while someone is typing or working a select.
        if (/^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)) {
            return;
        }
        var direction = {ArrowLeft: 'prev', ArrowRight: 'next'}[event.key];
        var href = direction && diffStepHref(direction) && $(BUTTONS[direction]).attr('href');
        if (href) {
            event.preventDefault();
            window.location.href = href;
        }
    });
}

// The seven diff options collapse behind the 'Filters' button so the sticky bar
// stays one toolbar row. Wired up here rather than purely in CSS: until this
// runs the fieldset is inline and the toggle hidden, so with scripting off the
// options are still reachable and still submit with the form.
function setupDiffFilters() {
    var $header = $('#diff-header');
    var $toggle = $('#diff-filters-toggle');
    var $panel = $('#diff-style');
    if (!$header.length || !$toggle.length || !$panel.length) {
        return;
    }
    var header = $header[0], toggle = $toggle[0], panel = $panel[0];

    $header.addClass('diff-filters-js');

    function isOpen() {
        return $header.hasClass('diff-filters-open');
    }

    var EDGE_GAP = 8;   // keep the panel clear of the viewport edges
    var BUTTON_GAP = 4; // between the toggle and the panel

    // position: fixed, because #diff-header's overflow: auto would clip an absolute
    // panel - which means parking it by hand, and that scrolling will never bring a
    // row hanging off the bottom back into reach. So it has to fit at placement time
    // or not at all: cap it to the room there is and let it scroll (see diff.scss).
    function place() {
        var button = toggle.getBoundingClientRect();
        // A fixed element is positioned against the layout viewport, but iOS
        // shrinks the *visual* one behind its toolbars, so budget with whichever
        // is smaller.
        var viewportHeight = document.documentElement.clientHeight;
        if (window.visualViewport) {
            viewportHeight = Math.min(viewportHeight, window.visualViewport.height);
        }

        // Measure unconstrained: a cap left over from the previous placement would
        // otherwise read back as the panel's natural height.
        panel.style.maxHeight = '';

        // Pick the roomier side rather than assume one: below used to be roomier by
        // construction, but diff.scss's short-viewport breakpoint drops the bar's
        // 50svh cap and at 280x300 above wins 147.6px to 104.2px.
        var roomBelow = viewportHeight - button.bottom - BUTTON_GAP - EDGE_GAP;
        var roomAbove = button.top - BUTTON_GAP - EDGE_GAP;
        var above = roomAbove > roomBelow;
        var room = above ? roomAbove : roomBelow;

        if (panel.offsetHeight > room) {
            // max-height caps the content box, and the panel must stay content-box
            // (border-box would fold the padding into min-width and narrow it by
            // 24px) - so subtract its own padding and borders.
            var style = window.getComputedStyle(panel);
            var trim = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom) +
                       parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth);
            panel.style.maxHeight = Math.max(room - trim, 0) + 'px';
        }

        // offsetHeight after the cap: parking above measures from the panel's bottom.
        var top = above ? button.top - BUTTON_GAP - panel.offsetHeight
                        : button.bottom + BUTTON_GAP;
        panel.style.top = top + 'px';

        var available = document.documentElement.clientWidth - panel.offsetWidth - EDGE_GAP;
        var left = Math.max(EDGE_GAP, Math.min(button.left, available));

        // The panel paints the page's own backdrop (see diff.scss), aligned by
        // geometry because iOS Safari ignores background-attachment: fixed. Negative
        // because the copy's top-left corner belongs at the viewport's.
        $panel.css({left: left + 'px', backgroundPosition: (-left) + 'px ' + (-top) + 'px'});
    }

    function open() {
        $header.addClass('diff-filters-open');
        $toggle.attr('aria-expanded', 'true');
        place();
    }

    function close(restoreFocus) {
        if (!isOpen()) {
            return;
        }
        $header.removeClass('diff-filters-open');
        $toggle.attr('aria-expanded', 'false');
        if (restoreFocus) {
            $toggle.trigger('focus');
        }
    }

    $toggle.on('click', function (event) {
        event.preventDefault();
        if (isOpen()) {
            close(false);
        } else {
            open();
        }
    });

    $(document).on('click', function (event) {
        if (isOpen() && !panel.contains(event.target) && !toggle.contains(event.target)) {
            close(false);
        }
    });

    $(document).on('keydown', function (event) {
        if (event.key === 'Escape') {
            close(true);
        }
    });

    // A tab switch hides #settings and the panel with it, so drop the open state
    // rather than leave aria-expanded lying.
    $(window).on('hashchange', function () {
        close(false);
    });

    $(window).on('resize', function () {
        if (isOpen()) {
            place();
        }
    });

    // The button can drift out from under the fixed panel two ways: #settings
    // scrolling inside a sticky bar (16px at 390x390, 30px at 320x480), or the whole
    // bar scrolling away below diff.scss's max-height: 500px breakpoint. Opposite
    // causes, one follow/close rule; each closing test is inert in the other mode.
    function followButton() {
        if (!isOpen()) {
            return;
        }
        var bar = header.getBoundingClientRect();
        var button = toggle.getBoundingClientRect();
        var viewportHeight = document.documentElement.clientHeight;
        if (button.bottom <= bar.top || button.top >= bar.bottom ||
            button.bottom <= 0 || button.top >= viewportHeight) {
            close(false);
        } else {
            place();
        }
    }

    // Native, not jQuery: .on() cannot pass passive or capture. Capture is required
    // because scroll does not bubble and the element that scrolls is #settings, a
    // descendant; the window registration covers the static mode's document scroll.
    header.addEventListener('scroll', followButton, {passive: true, capture: true});
    window.addEventListener('scroll', followButton, {passive: true});
    // On iOS the visual viewport shrinks on its own - a toolbar or the keyboard -
    // without resizing the layout viewport, so no window resize fires and the cap
    // place() budgeted stays wrong. Reproduced in Chromium via CDP pinch-zoom.
    if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', function () {
            if (isOpen()) {
                place();
            }
        });
    }
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
    $(window).on('hashchange', function () {
        toggle(location.hash);
        realignPane();
    });

    // Where the last alignment we performed left the page, so a later one can tell
    // "still where we put them" from "the reader has moved since", and the
    // scroll-margin-top it was computed against.
    var alignedY = null;
    var alignedMargin = null;

    function targetPane() {
        var pane = location.hash.length > 1 &&
            document.getElementById(location.hash.slice(1));
        return pane && pane.classList.contains('tab-pane-inner') ? pane : null;
    }

    // The fragment jump runs before toggle() hides #settings, which collapses the
    // ~8000px document; the engine then clamps its held offset rather than re-running
    // the jump, and on iOS that clamp is never 0. So re-run it once the layout has
    // settled. scrollIntoView, not scrollTo(0, 0): .tab-pane-inner already declares
    // the sticky stack's offset as scroll-margin-top. setTimeout(0) rather than rAF,
    // because that margin resolves against --diff-header-height, which
    // diff-render.js's ResizeObserver updates after frame callbacks have run.
    function realignPane() {
        var pane = targetPane();
        if (!pane) {
            return;
        }
        setTimeout(function () {
            alignedMargin = parseFloat(getComputedStyle(pane).scrollMarginTop);
            pane.scrollIntoView({block: 'start', inline: 'nearest'});
            alignedY = window.scrollY;
        }, 0);
    }

    // The load path is stale for a nearer reason: tabs.js rewrites an empty hash and
    // the browser jumps before diff-render.js has measured the bar, so
    // scroll-margin-top is still on its --diff-header-height: 0 fallback. Traced at
    // 844x390: landed at scrollY 231 against a 16px margin that then became 202px.
    // Below the short-viewport breakpoint the bar is in flow, so that puts every
    // control off the top of the page. Re-run when the bar resizes - comparing the
    // margin, so it only fires on a real change - and only while the reader is still
    // where we left them, since rotating the phone resizes the bar too.
    var bar = document.getElementById('diff-header');
    if (bar && typeof ResizeObserver !== 'undefined') {
        new ResizeObserver(function () {
            var pane = targetPane();
            if (!pane) {
                return;
            }
            if (alignedY !== null && Math.abs(window.scrollY - alignedY) > 2) {
                return;
            }
            var margin = parseFloat(getComputedStyle(pane).scrollMarginTop);
            if (alignedMargin !== null && Math.abs(margin - alignedMargin) < 0.5) {
                return;
            }
            realignPane();
        }).observe(bar);
    }

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

    // We could also add the 'touchend' event for touch devices, but since most
    // iOS/Android browsers already show a dialog when you select text (often with a
    // Share option) we'll skip that. mouseup goes on the page rather than the
    // article, because they might 'mouse up' outside it.
    $('#difference').on('mousedown', clean);
    $('.difference-page').on('mouseup', dragTextHandler);

    $('#highlightSnippetActions a').on('click', function (e) {
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

    $(window).on('keydown', function (e) {
        if (e.key === 'Escape') {
            clean();
        }
    });

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
