// Socket.IO client-side integration for changedetection.io

$(document).ready(function() {
  // Try to create the socket connection to port 5005 - if it fails, the site will still work normally
  try {
    // Connect to the dedicated Socket.IO server on port 5005
    const socket = io('http://127.0.0.1:5005');
    
    // Connection status logging
    socket.on('connect', function() {
      console.log('Socket.IO connected');
    });
    
    socket.on('disconnect', function() {
      console.log('Socket.IO disconnected');
    });
    
    // Listen for periodically emitted watch data
    socket.on('watch_data', function(watches) {
      console.log('Received watch data updates');
      
      // First, remove checking-now class from all rows
      $('.checking-now').removeClass('checking-now');
      
      // Update all watches with their current data
      watches.forEach(function(watch) {
        const $watchRow = $('tr[data-watch-uuid="' + watch.uuid + '"]');
        if ($watchRow.length) {
          updateWatchRow($watchRow, watch);
        }
      });
    });
    
    // Function to update a watch row with new data
    function updateWatchRow($row, data) {
      // Update the last-checked time
      const $lastChecked = $row.find('.last-checked');
      if ($lastChecked.length && data.last_checked) {
        // Format as timeago if we have the timeago library available
        if (typeof timeago !== 'undefined') {
          $lastChecked.text(timeago.format(data.last_checked, Date.now()/1000));
        } else {
          // Simple fallback if timeago isn't available
          const date = new Date(data.last_checked * 1000);
          $lastChecked.text(date.toLocaleString());
        }
      }
      
      // Toggle the unviewed class based on viewed status
      $row.toggleClass('unviewed', data.viewed === false);
      
      // If the watch is currently being checked
      $row.toggleClass('checking-now', data.checking === true);
      
      // If a change was detected and not viewed, add highlight effect
      if (data.history_n > 0 && data.viewed === false) {
        // Don't add the highlight effect too often
        if (!$row.hasClass('socket-highlight')) {
          $row.addClass('socket-highlight');
          setTimeout(function() {
            $row.removeClass('socket-highlight');
          }, 2000);
          
          console.log('New change detected for:', data.title || data.url);
        }
        
        // Update any change count indicators if present
        const $changeCount = $row.find('.change-count');
        if ($changeCount.length) {
          $changeCount.text(data.history_n);
        }
      }
    }
  } catch (e) {
    // If Socket.IO fails to initialize, just log it and continue
    console.log('Socket.IO initialization error:', e);
  }
});