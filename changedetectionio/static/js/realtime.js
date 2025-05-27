// Socket.IO client-side integration for changedetection.io

$(document).ready(function () {

    function bindAjaxHandlerButtonsEvents() {
        $('.ajax-op').on('click.ajaxHandlerNamespace', function (e) {
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
    }


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
                reconnectionAttempts: 15
            });

            // Connection status logging
            socket.on('connect', function () {
                console.log('Socket.IO connected with path:', socketio_url);
                console.log('Socket transport:', socket.io.engine.transport.name);
                bindAjaxHandlerButtonsEvents();
            });

            socket.on('connect_error', function(error) {
                console.error('Socket.IO connection error:', error);
            });

            socket.on('connect_timeout', function() {
                console.error('Socket.IO connection timeout');
            });

            socket.on('error', function(error) {
                console.error('Socket.IO error:', error);
            });

            socket.on('disconnect', function (reason) {
                console.log('Socket.IO disconnected, reason:', reason);
                $('.ajax-op').off('.ajaxHandlerNamespace')
            });

            socket.on('queue_size', function (data) {
                console.log(`${data.event_timestamp} - Queue size update: ${data.q_length}`);
                // Update queue size display if implemented in the UI
            })

            // Listen for periodically emitted watch data
            console.log('Adding watch_update event listener');

            socket.on('watch_update', function (data) {
                const watch = data.watch;
                const general_stats = data.general_stats;

                // Log the entire watch object for debugging
                console.log('!!! WATCH UPDATE EVENT RECEIVED !!!');
                console.log(`${watch.event_timestamp} - Watch update ${watch.uuid} - Checking now - ${watch.checking_now} - UUID in URL ${window.location.href.includes(watch.uuid)}`);
                console.log('Watch data:', watch);
                console.log('General stats:', general_stats);
                
                // Updating watch table rows
                const $watchRow = $('tr[data-watch-uuid="' + watch.uuid + '"]');
                console.log('Found watch row elements:', $watchRow.length);
                
                if ($watchRow.length) {
                    $($watchRow).toggleClass('checking-now', watch.checking_now);
                    $($watchRow).toggleClass('queued', watch.queued);
                    $($watchRow).toggleClass('unviewed', watch.unviewed);
                    $($watchRow).toggleClass('has-error', watch.has_error);
                    $($watchRow).toggleClass('notification_muted', watch.notification_muted);
                    $($watchRow).toggleClass('paused', watch.paused);
                    $($watchRow).toggleClass('has-thumbnail', watch.thumbnail !== undefined);

                    $('td.title-col .error-text', $watchRow).html(watch.error_text)
                    $('img.thumbnail', $watchRow).attr('src', watch.thumbnail);

                    $('td.last-changed', $watchRow).text(watch.last_checked_text)

                    $('td.last-checked .innertext', $watchRow).text(watch.last_checked_text)
                    $('td.last-checked', $watchRow).data('timestamp', watch.last_checked).data('fetchduration', watch.fetch_time);
                    $('td.last-checked', $watchRow).data('eta_complete', watch.last_checked + watch.fetch_time);
                    
                    console.log('Updated UI for watch:', watch.uuid);
                }

                // Tabs at bottom of list
                $('#post-list-mark-views').toggleClass("has-unviewed", general_stats.has_unviewed);
                $('#post-list-with-errors').toggleClass("has-error", general_stats.count_errors !== 0)
                $('#post-list-with-errors a').text(`With errors (${ general_stats.count_errors })`);

                $('body').toggleClass('checking-now', watch.checking_now && window.location.href.includes(watch.uuid));
            });

        } catch (e) {
            // If Socket.IO fails to initialize, just log it and continue
            console.log('Socket.IO initialization error:', e);
        }
    }
});