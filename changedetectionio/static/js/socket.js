// Socket.IO client-side integration for changedetection.io
// @todo only bind ajax if the socket server attached success.

$(document).ready(function () {
    $('.ajax-op').click(function (e) {
        e.preventDefault();
        $.ajax({
            type: "POST",
            url: ajax_toggle_url,
            data: {'op': $(this).data('op'), 'uuid': $(this).closest('tr').data('watch-uuid')},
            statusCode: {
                400: function () {
                    // More than likely the CSRF token was lost when the server restarted
                    alert("There was a problem processing the request, please reload the page.");
                }
            }
        });
        return false;
    });


    // Only try to connect if authentication isn't required or user is authenticated
    // The 'is_authenticated' variable will be set in the template
    if (typeof is_authenticated !== 'undefined' ? is_authenticated : true) {
        // Try to create the socket connection to the SocketIO server - if it fails, the site will still work normally
        try {
            // Connect to Socket.IO on the same host/port, with path from template
            const socket = io({
                path: socketio_url,  // This will be the path prefix like "/app/socket.io" from the template
                transports: ['polling', 'websocket'],  // Try WebSocket but fall back to polling
                reconnectionDelay: 1000,
                reconnectionAttempts: 5
            });

            // Connection status logging
            socket.on('connect', function () {
                console.log('Socket.IO connected');
            });

            socket.on('disconnect', function () {
                console.log('Socket.IO disconnected');
            });

            socket.on('queue_size', function (data) {
                console.log(`${data.event_timestamp} - Queue size update: ${data.q_length}`);
                // Update queue size display if implemented in the UI
            })

            // Listen for periodically emitted watch data
            socket.on('watch_update', function (watch) {
                console.log(`${watch.event_timestamp} - Watch update ${watch.uuid} - Checking now - ${watch.checking_now} - UUID in URL ${window.location.href.includes(watch.uuid)}`);

                // Updating watch table rows
                const $watchRow = $('tr[data-watch-uuid="' + watch.uuid + '"]');
                if ($watchRow.length) {
                    $($watchRow).toggleClass('checking-now', watch.checking_now);
                    $($watchRow).toggleClass('queued', watch.queued);
                    $($watchRow).toggleClass('unviewed', watch.unviewed);
                    $($watchRow).toggleClass('error', watch.has_error);
                    $($watchRow).toggleClass('notification_muted', watch.notification_muted);
                    $($watchRow).toggleClass('paused', watch.paused);

                    $('td.error', $watchRow).text(watch.last_error_text)

                    $('td.last-changed', $watchRow).text(watch.last_checked_text)

                    $('td.last-checked .innertext', $watchRow).text(watch.last_checked_text)
                    $('td.last-checked', $watchRow).data('timestamp', watch.last_checked).data('fetchduration', watch.fetch_time);
                    $('td.last-checked', $watchRow).data('eta_complete', watch.last_checked + watch.fetch_time);
                }
                $('body').toggleClass('checking-now', watch.checking_now && window.location.href.includes(watch.uuid));
            });

        } catch (e) {
            // If Socket.IO fails to initialize, just log it and continue
            console.log('Socket.IO initialization error:', e);
        }
    }
});