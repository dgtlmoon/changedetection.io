$(document).ready(function () {

    // Find all <span> elements inside pre#difference
    var inputs = $('#difference span').toArray();
    inputs.current = 0;

    // Setup visual minimap of difference locations (cells are pre-built in Python)
    var $visualizer = $('#cell-diff-jump-visualiser');
    var $difference = $('#difference');
    var $cells = $visualizer.find('> div');
    var visualizerResolutionCells = $cells.length;
    var cellHeight;

    var header = document.getElementById('diff-header');
    // The app top menu, sticky above #diff-header on the diff page.
    var appHeader = document.querySelector('.app-main > .header');

    // Controls can wrap or disappear when switching tabs, and the top menu
    // rewraps on narrow viewports. Keep each sticky layer, the minimap and the
    // anchor links below the actual measured heights instead of fixed offsets.
    // Order matters: #diff-header's max-height is calc(50dvh - the app header),
    // so store that first and measure the diff header against the new cap. The
    // other way round reads it under the previous cap and one pass is not enough
    // to settle.
    function updateHeaderHeight() {
        if (appHeader) {
            document.body.style.setProperty('--app-header-height', appHeader.offsetHeight + 'px');
        }
        if (header) {
            document.body.style.setProperty('--diff-header-height', header.offsetHeight + 'px');
        }
    }
    if (header || appHeader) {
        // Measure once regardless of observer support, so the offsets are never
        // left at their 0 fallback.
        updateHeaderHeight();
        if (typeof ResizeObserver !== 'undefined') {
            var headerObserver = new ResizeObserver(updateHeaderHeight);
            if (header) headerObserver.observe(header);
            if (appHeader) headerObserver.observe(appHeader);
        } else {
            // Without it, catch the two things that actually resize the bars:
            // the window rewrapping them, and the tab switch that shows or hides
            // #settings. diff-overview.js toggles that from its own hashchange
            // handler, so defer past it rather than depend on listener order.
            $(window).on('resize.diffheader', updateHeaderHeight.debounce(100));
            $(window).on('hashchange.diffheader', function () {
                setTimeout(updateHeaderHeight, 0);
            });
            // Opening a link straight at #screenshot / #extract hides #settings
            // from diff-overview.js's ready handler, with no hashchange to
            // follow. Re-measure once the whole ready pass has run.
            setTimeout(updateHeaderHeight, 0);
        }
    }

    // Centre of the region left visible below the sticky stack, not of the whole
    // viewport - every sticky layer above the diff has to be counted or jumps
    // land half its height too high.
    function viewportCenterOffset() {
        var appHeaderHeight = appHeader ? appHeader.offsetHeight : 0;
        var headerHeight = header ? header.offsetHeight : 0;
        var visualizerHeight = $visualizer.is(':visible') ? $visualizer.outerHeight() : 0;
        return (appHeaderHeight + headerHeight + visualizerHeight + $(window).height()) / 2;
    }

    if ($difference.length && visualizerResolutionCells > 0) {
        var docHeight = $difference[0].scrollHeight;
        cellHeight = docHeight / visualizerResolutionCells;

        // Add click handlers to pre-built cells
        $cells.each(function(i) {
            $(this).data('cellIndex', i);
            $(this).on('click', function() {
                var cellIndex = $(this).data('cellIndex');
                var targetPositionInDifference = cellIndex * cellHeight;

                // Scroll so target is at viewport center (where eyes expect it)
                window.scrollTo({
                    top: $difference.offset().top + targetPositionInDifference - viewportCenterOffset(),
                    behavior: "smooth"
                });
            });
        });
    }

    $('#jump-next-diff').click(function () {
        if (!inputs || inputs.length === 0) return;

        // Find the next change after current scroll position
        var currentScrollPos = $(window).scrollTop();
        var currentCenter = currentScrollPos + viewportCenterOffset();

        // Add small buffer (50px) to jump past changes already near center
        var searchFromPosition = currentCenter + 50;

        var nextElement = null;
        for (var i = 0; i < inputs.length; i++) {
            var elementTop = $(inputs[i]).offset().top;
            if (elementTop > searchFromPosition) {
                nextElement = inputs[i];
                break;
            }
        }

        // If no element found ahead, wrap to first element
        if (!nextElement) {
            nextElement = inputs[0];
        }

        // Scroll to position the element at viewport center
        var elementTop = $(nextElement).offset().top;
        var targetScrollPos = elementTop - viewportCenterOffset();

        window.scrollTo({
            top: targetScrollPos,
            behavior: "smooth",
        });
    });

    // Track current scroll position in visualizer
    function updateVisualizerPosition() {
        if (!$difference.length || visualizerResolutionCells === 0) return;

        var scrollTop = $(window).scrollTop();
        var viewportHeight = $(window).height();
        var viewportCenter = scrollTop + viewportCenterOffset();
        var differenceTop = $difference.offset().top;
        var differenceHeight = $difference[0].scrollHeight;
        var positionInDifference = viewportCenter - differenceTop;

        // Handle edge case: if we're at max scroll, show last cell
        // This prevents shorter documents from never reaching 100%
        var maxScrollTop = $(document).height() - viewportHeight;
        var isAtBottom = scrollTop >= maxScrollTop - 10; // 10px tolerance

        // Calculate which cell we're currently viewing
        var currentCell;
        if (isAtBottom) {
            currentCell = visualizerResolutionCells - 1;
        } else {
            currentCell = Math.floor(positionInDifference / cellHeight);
            currentCell = Math.max(0, Math.min(currentCell, visualizerResolutionCells - 1));
        }

        // Remove previous active marker and add to current cell
        $visualizer.find('> div').removeClass('current-position');
        $visualizer.find('> div').eq(currentCell).addClass('current-position');
    }

    // Recalculate cellHeight on window resize
    function handleResize() {
        if ($difference.length) {
            var docHeight = $difference[0].scrollHeight;
            cellHeight = docHeight / visualizerResolutionCells;
            updateVisualizerPosition();
        }
    }

    // Debounce scroll and resize events to reduce CPU usage
    $(window).on('scroll', updateVisualizerPosition.debounce(5));
    $(window).on('resize', handleResize.debounce(100));

    // Initial scroll to specific line if requested
    if (typeof initialScrollToLineNumber !== 'undefined' && initialScrollToLineNumber !== null && $difference.length) {
        // Convert line number to text position and scroll to it
        var diffText = $difference.text();
        var lines = diffText.split('\n');

        if (initialScrollToLineNumber > 0 && initialScrollToLineNumber <= lines.length) {
            // Calculate character position of the target line
            var charPosition = 0;
            for (var i = 0; i < initialScrollToLineNumber - 1; i++) {
                charPosition += lines[i].length + 1; // +1 for newline
            }

            // Estimate vertical position based on average line height
            var totalChars = diffText.length;
            var totalHeight = $difference[0].scrollHeight;
            var estimatedTop = (charPosition / totalChars) * totalHeight;

            // Scroll to position with line at viewport center
            setTimeout(function() {
                window.scrollTo({
                    top: $difference.offset().top + estimatedTop - viewportCenterOffset(),
                    behavior: "smooth"
                });
            }, 100); // Small delay to ensure page is fully loaded
        }
    }

    // Initial position update
    if ($difference.length && cellHeight) {
        updateVisualizerPosition();
    }

    function changed() {
        //$('#jump-next-diff').click();
    }

});
