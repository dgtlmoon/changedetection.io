$(document).ready(function() {
    // Global variables for resize functionality
    let isResizing = false;
    let initialX, initialLeftWidth;
    
    // Setup document-wide mouse move and mouse up handlers
    $(document).on('mousemove', handleMouseMove);
    $(document).on('mouseup', function() {
        isResizing = false;
    });
    
    // Handle mouse move for resizing
    function handleMouseMove(e) {
        if (!isResizing) return;
        
        const $container = $('#filters-and-triggers > div');
        const containerWidth = $container.width();
        const diffX = e.clientX - initialX;
        const newLeftWidth = ((initialLeftWidth + diffX) / containerWidth) * 100;
        
        // Limit the minimum width percentage
        if (newLeftWidth > 20 && newLeftWidth < 80) {
            $('#edit-text-filter').css('flex', `0 0 ${newLeftWidth}%`);
            $('#text-preview').css('flex', `0 0 ${100 - newLeftWidth}%`);
        }
    }
    
    // Function to create and setup the resizer
    function setupResizer() {
        // Only proceed if text-preview is visible
        if (!$('#text-preview').is(':visible')) return;
        
        // Don't add another resizer if one already exists
        if ($('#column-resizer').length > 0) return;
        
        // Create resizer element
        const $resizer = $('<div>', {
            class: 'column-resizer',
            id: 'column-resizer'
        });
        
        // Insert before the text preview div
        const $container = $('#filters-and-triggers > div');
        if ($container.length) {
            $resizer.insertBefore('#text-preview');
            
            // Setup mousedown handler for the resizer
            $resizer.on('mousedown', function(e) {
                isResizing = true;
                initialX = e.clientX;
                initialLeftWidth = $('#edit-text-filter').width();
                
                // Prevent text selection during resize
                e.preventDefault();
            });
        }
    }
    
    // Setup resizer when preview is activated
    $('#activate-text-preview').on('click', function() {
        // Give it a small delay to ensure the preview is visible
        setTimeout(setupResizer, 100);
    });
    
    // Also setup resizer when the filters-and-triggers tab is clicked
    $('#filters-and-triggers-tab a').on('click', function() {
        // Give it a small delay to ensure everything is loaded
        setTimeout(setupResizer, 100);
    });
    
    // Run the setupResizer function when the page is fully loaded
    // to ensure it's added if the text-preview is already visible
    setTimeout(setupResizer, 500);
    
    // Handle window resize events
    $(window).on('resize', function() {
        // Make sure the resizer is added if text-preview is visible
        if ($('#text-preview').is(':visible')) {
            setupResizer();
        }
    });
    
    // Keep checking if the resizer needs to be added
    // This ensures it's restored if something removes it
    setInterval(function() {
        if ($('#text-preview').is(':visible')) {
            setupResizer();
        }
    }, 500);
    
    // Add a MutationObserver to watch for DOM changes
    // This will help restore the resizer if it gets removed
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            if (mutation.type === 'childList' && 
                $('#text-preview').is(':visible') && 
                $('#column-resizer').length === 0) {
                setupResizer();
            }
        });
    });
    
    // Start observing the container for DOM changes
    observer.observe(document.getElementById('filters-and-triggers'), {
        childList: true,
        subtree: true
    });
});