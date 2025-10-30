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

    if ($difference.length && visualizerResolutionCells > 0) {
        var docHeight = $difference[0].scrollHeight;
        cellHeight = docHeight / visualizerResolutionCells;

        // Add click handlers to pre-built cells
        $cells.each(function(i) {
            $(this).data('cellIndex', i);
            $(this).on('click', function() {
                var cellIndex = $(this).data('cellIndex');
                var targetPositionInDifference = cellIndex * cellHeight;
                var viewportHeight = $(window).height();

                // Scroll so target is at viewport center (where eyes expect it)
                window.scrollTo({
                    top: $difference.offset().top + targetPositionInDifference - (viewportHeight / 2),
                    behavior: "smooth"
                });
            });
        });
    }

    $('#jump-next-diff').click(function () {
        if (!inputs || inputs.length === 0) return;

        // Find the next change after current scroll position
        var currentScrollPos = $(window).scrollTop();
        var viewportHeight = $(window).height();
        var currentCenter = currentScrollPos + (viewportHeight / 2);

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
        var targetScrollPos = elementTop - (viewportHeight / 2);

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
        var viewportCenter = scrollTop + (viewportHeight / 2);
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
            var viewportHeight = $(window).height();
            setTimeout(function() {
                window.scrollTo({
                    top: $difference.offset().top + estimatedTop - (viewportHeight / 2),
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

