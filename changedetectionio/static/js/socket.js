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
      if ($lastChecked.length) {
        // Update data-timestamp attribute
        $lastChecked.attr('data-timestamp', data.last_checked);
        
        // Only show timeago if not currently checking
        if (!data.checking) {
          let $timeagoSpan = $lastChecked.find('.timeago');
          
          // If there's no timeago span yet, create one
          if (!$timeagoSpan.length) {
            $lastChecked.html('<span class="timeago"></span>');
            $timeagoSpan = $lastChecked.find('.timeago');
          }
          
          if (data.last_checked > 0) {
            // Format as timeago if we have the timeago library available
            if (typeof timeago !== 'undefined') {
              $timeagoSpan.text(timeago.format(data.last_checked * 1000));
            } else {
              // Simple fallback if timeago isn't available
              const date = new Date(data.last_checked * 1000);
              $timeagoSpan.text(date.toLocaleString());
            }
          } else {
            $lastChecked.text('Not yet');
          }
        }
      }
      
      // Update the last-changed time
      const $lastChanged = $row.find('.last-changed');
      if ($lastChanged.length && data.last_changed) {
        // Update data-timestamp attribute
        $lastChanged.attr('data-timestamp', data.last_changed);
        
        // Only update the text if we have history
        if (data.history_n >= 2 && data.last_changed > 0) {
          let $timeagoSpan = $lastChanged.find('.timeago');
          
          // If there's no timeago span yet, create one
          if (!$timeagoSpan.length) {
            $lastChanged.html('<span class="timeago"></span>');
            $timeagoSpan = $lastChanged.find('.timeago');
          }
          
          // Format as timeago
          if (typeof timeago !== 'undefined') {
            $timeagoSpan.text(timeago.format(data.last_changed * 1000));
          } else {
            // Simple fallback if timeago isn't available
            const date = new Date(data.last_changed * 1000);
            $timeagoSpan.text(date.toLocaleString());
          }
        } else {
          $lastChanged.text('Not yet');
        }
      }
      
      // Toggle the unviewed class based on viewed status
      $row.toggleClass('unviewed', data.unviewed_history === false);
      
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