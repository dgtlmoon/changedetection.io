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

    var EDGE_GAP = 8;   // keep the panel clear of the viewport edges
    var BUTTON_GAP = 4; // between the toggle and the panel

    // The panel is position: fixed - #diff-header's overflow: auto would clip an
    // absolutely positioned one - so it has to be parked under the button by
    // hand, and kept inside the viewport on a small screen. Fixed also means the
    // page scrolling underneath will never bring a row that hangs off the bottom
    // back into reach, so the height has to fit at placement time or not at all:
    // below the button there is always at least half the viewport, because the
    // bar's own cap keeps its bottom edge inside 50svh - what there is not
    // always enough of is room for the whole seven-row panel. Cap it to the
    // space there is and let it scroll (see diff.scss). Parking it at full
    // height put the last three filters off-screen and unclickable in a
    // landscape phone viewport.
    function place() {
        var button = toggle.getBoundingClientRect();
        // A fixed element is positioned against the layout viewport, but iOS
        // shrinks the *visual* one behind its toolbars, so budget with
        // whichever is smaller.
        var viewportHeight = document.documentElement.clientHeight;
        if (window.visualViewport) {
            viewportHeight = Math.min(viewportHeight, window.visualViewport.height);
        }

        // Measure unconstrained: a cap left over from the previous placement
        // would otherwise read back as the panel's natural height.
        panel.style.maxHeight = '';
        var room = viewportHeight - button.bottom - BUTTON_GAP - EDGE_GAP;

        if (panel.offsetHeight > room) {
            // max-height caps the content box, and the panel is content-box
            // (leave it that way: border-box would fold the padding into the
            // min-width too and narrow the panel by 24px). Hand it the room
            // less its own padding and borders so offsetHeight lands on room.
            var style = window.getComputedStyle(panel);
            var trim = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom) +
                       parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth);
            panel.style.maxHeight = Math.max(room - trim, 0) + 'px';
        }

        var top = button.bottom + BUTTON_GAP;
        panel.style.top = top + 'px';

        var available = document.documentElement.clientWidth - panel.offsetWidth - EDGE_GAP;
        var left = Math.max(EDGE_GAP, Math.min(button.left, available));
        panel.style.left = left + 'px';

        // The panel paints the page's own backdrop (see diff.scss), and that
        // copy is aligned by geometry rather than by background-attachment:
        // fixed, which iOS Safari ignores. The two sticky bars can state their
        // viewport offset in CSS because it never changes; this one cannot -
        // it is wherever the button just was - so hand it the offset here. Both
        // values are negative: the copy's top-left corner belongs at the
        // viewport's, which is up and to the left of the panel.
        panel.style.backgroundPosition = (-left) + 'px ' + (-top) + 'px';
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
    // viewport position as the *page* scrolls. A tab switch hides #settings, and
    // the panel with it, so drop the open state rather than leave aria-expanded
    // lying.
    window.addEventListener('resize', function () {
        if (isOpen()) {
            place();
        }
    });
    // The bar contains a scroll container though - overflow enforces the 50svh
    // cap - so on a short viewport the button can scroll under a panel that,
    // being fixed, stays where it was put: measured 16px of drift at 390x390 and
    // 30px at 320x480, enough to leave the popover pointing at the wrong
    // control. Follow the button, and close once it has scrolled out of the bar
    // entirely rather than park the panel over the title.
    //
    // Capture, not bubble: scroll events do not bubble, and the container that
    // actually scrolls is #settings (diff.scss keeps the tab row out of the
    // budget by shrinking that one child), which is a descendant. Capturing on
    // the bar catches it and #diff-header's own last-resort scroll alike.
    header.addEventListener('scroll', function () {
        if (!isOpen()) {
            return;
        }
        var bar = header.getBoundingClientRect();
        var button = toggle.getBoundingClientRect();
        if (button.bottom <= bar.top || button.top >= bar.bottom) {
            close(false);
        } else {
            place();
        }
    }, {passive: true, capture: true});
    // place() budgets against the *visual* viewport when it is the smaller of
    // the two, and on iOS that one can shrink on its own - a toolbar expanding
    // or the on-screen keyboard coming up moves it without resizing the layout
    // viewport, so no window resize fires. Without this the cap stays at the
    // height it was placed with and the bottom rows sit behind the chrome
    // again. Measured in Chromium via CDP pinch-zoom, which splits the two
    // viewports the same way: the panel kept a 195px cap against a viewport
    // that had become 260px tall and overhung it by 122px.
    if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', function () {
            if (isOpen()) {
                place();
            }
        });
    }
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
        realignPane();
    }, false);

    // The browser runs the fragment jump first; only afterwards does toggle()
    // hide #settings and the outgoing pane stop being :target, which collapses
    // the text diff's ~8000px document to a fraction of a screen. The engine is
    // then holding a scroll offset for a page that no longer exists and clamps
    // it to the new maximum instead of re-running the jump. On iOS that maximum
    // is never 0 - styles.scss floors the shell at min-height: 100vh and 100vh
    // there is the toolbar-collapsed viewport - so you arrive on the Screenshot
    // tab with its first line behind the bar. Measured off a device recording:
    // about one line, held for roughly a second before Safari re-settled it.
    //
    // So re-run the jump once the layout has stopped moving. scrollIntoView, not
    // scrollTo(0, 0): .tab-pane-inner already declares the offset the sticky
    // stack needs as scroll-margin-top, and this is the same alignment the
    // browser was asked for, just applied to the layout that actually resulted.
    //
    // setTimeout(0) rather than requestAnimationFrame: that scroll-margin-top is
    // written in terms of --diff-header-height, which diff-render.js's
    // ResizeObserver updates during the rendering update - after animation frame
    // callbacks have already run, and hiding #settings is exactly what changes
    // it.
    function realignPane() {
        var pane = location.hash.length > 1 &&
            document.getElementById(location.hash.slice(1));
        if (!pane || !pane.classList.contains('tab-pane-inner')) {
            return;
        }
        setTimeout(function () {
            pane.scrollIntoView({block: 'start', inline: 'nearest'});
        }, 0);
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
