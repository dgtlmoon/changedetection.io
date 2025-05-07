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
    socket.on('watch_update', function(watch) {
      console.log(`Watch update ${watch.uuid}`);


      const $watchRow = $('tr[data-watch-uuid="' + watch.uuid + '"]');
      if ($watchRow.length) {
        $($watchRow).toggleClass('checking-now', watch.checking_now);
        $($watchRow).toggleClass('queued', watch.queued);
        $($watchRow).toggleClass('unviewed', watch.unviewed);
      }
    });

  } catch (e) {
    // If Socket.IO fails to initialize, just log it and continue
    console.log('Socket.IO initialization error:', e);
  }
});