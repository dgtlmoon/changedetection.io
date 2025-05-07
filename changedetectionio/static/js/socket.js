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

  socket.on('checking_now', function(uuid_list) {
    console.log("Got checking now update");
      // Remove 'checking-now' class where it should no longer be
      $('.watch-table tbody tr.checking-now').each(function() {
          if (!uuid_list.includes($(this).data('watch-uuid'))) {
              $(this).removeClass('checking-now');
          }
      });

      // Add the class on the rows where it should be
      uuid_list.forEach(function(uuid) {
          $('.watch-table tbody tr[data-watch-uuid="' + uuid + '"]').addClass('checking-now');
      });
  });

    // Listen for periodically emitted watch data
    socket.on('watch_data', function(watches) {
/*      console.log('Received watch data updates');

      
      // Update all watches with their current data
      watches.forEach(function(watch) {
        const $watchRow = $('tr[data-watch-uuid="' + watch.uuid + '"]');
        if ($watchRow.length) {
          updateWatchRow($watchRow, watch);
        }
      });*/
    });
    
    // Function to update a watch row with new data
    function updateWatchRow($row, data) {
      // Update the last-checked time
      return;
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

      
      // Toggle the unviewed class based on viewed status
//      $row.toggleClass('unviewed', data.unviewed_history === false);
      
      // If the watch is currently being checked
  //    $row.toggleClass('checking-now', data.checking === true);
    }
  } catch (e) {
    // If Socket.IO fails to initialize, just log it and continue
    console.log('Socket.IO initialization error:', e);
  }
});