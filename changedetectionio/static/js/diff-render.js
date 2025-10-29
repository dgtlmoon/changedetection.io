$(document).ready(function () {

    // Find all <span> elements inside pre#difference
    var inputs = $('#difference span').toArray();
    inputs.current = 0;

    // Build visual minimap of difference locations
    var $visualizer = $('#cell-diff-jump-visualiser');
    var $difference = $('#difference');
    var visualizerResolutionCells = 100; // Fixed resolution to prevent high CPU usage with many changes
    var cellHeight;
    var cellData = {}; // Map cell index to change type

    if ($difference.length && inputs.length) {
        var docHeight = $difference[0].scrollHeight;
        cellHeight = docHeight / visualizerResolutionCells;

        // Map each span to a cell with its type based on color
        var differenceTop = $difference.offset().top;
        $(inputs).each(function() {
            var spanTop = $(this).offset().top - differenceTop;
            var cellIndex = Math.min(Math.floor(spanTop / cellHeight), visualizerResolutionCells - 1);
            var bgColor = $(this).css('background-color');
            var changeType;

            // Determine type by background color
            if (bgColor === 'rgb(250, 218, 215)' || bgColor === '#fadad7') {
                changeType = 'deletion'; // Red background
            } else if (bgColor === 'rgb(234, 242, 194)' || bgColor === '#eaf2c2') {
                changeType = 'insertion'; // Green background
            } else {
                changeType = $(this).attr('role'); // Fallback to role attribute
            }

            // Track the type of change in each cell (prioritize mixed changes)
            if (!cellData[cellIndex]) {
                cellData[cellIndex] = changeType;
            } else if (cellData[cellIndex] !== changeType) {
                cellData[cellIndex] = 'mixed'; // Both deletion and insertion in same cell
            }
        });

        // Create cell strip
        for (var i = 0; i < visualizerResolutionCells; i++) {
            var $cell = $('<div>');
            var changeType = cellData[i];

            if (changeType === 'deletion') {
                $cell.addClass('deletion');
            } else if (changeType === 'insertion') {
                $cell.addClass('insertion');
            } else if (changeType === 'note') {
                $cell.addClass('note');
            } else if (changeType === 'mixed') {
                $cell.addClass('mixed');
            }

            // Add click handler to scroll to that position in the document
            $cell.data('cellIndex', i);
            $cell.on('click', function() {
                var cellIndex = $(this).data('cellIndex');
                var targetPositionInDifference = cellIndex * cellHeight;
                var viewportOffset = 150; // Keep change visible with 150px offset

                window.scrollTo({
                    top: $difference.offset().top + targetPositionInDifference - viewportOffset,
                    behavior: "smooth"
                });
            });

            $visualizer.append($cell);
        }
    }

    $('#jump-next-diff').click(function () {
        if (!inputs || inputs.length === 0) return;

        var element = inputs[inputs.current];
        var headerOffset = 80;
        var elementPosition = element.getBoundingClientRect().top;
        var offsetPosition = elementPosition - headerOffset + window.scrollY;

        window.scrollTo({
            top: offsetPosition,
            behavior: "smooth",
        });

        inputs.current++;
        if (inputs.current >= inputs.length) {
            inputs.current = 0;
        }
    });

    // Track current scroll position in visualizer
    function updateVisualizerPosition() {
        if (!$difference.length || visualizerResolutionCells === 0) return;

        var scrollTop = $(window).scrollTop();
        var differenceTop = $difference.offset().top;
        var positionInDifference = scrollTop - differenceTop;

        // Calculate which cell we're currently viewing
        var currentCell = Math.floor(positionInDifference / cellHeight);
        currentCell = Math.max(0, Math.min(currentCell, visualizerResolutionCells - 1));

        // Remove previous active marker and add to current cell
        $visualizer.find('> div').removeClass('current-position');
        $visualizer.find('> div').eq(currentCell).addClass('current-position');
    }

    // Debounce scroll event to reduce CPU usage
    $(window).on('scroll', updateVisualizerPosition.debounce(5));

    // Initial position update
    if ($difference.length && cellHeight) {
        updateVisualizerPosition();
    }

    function changed() {
        //$('#jump-next-diff').click();
    }

});

