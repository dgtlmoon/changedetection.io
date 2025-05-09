// Socket.IO client-side integration for changedetection.io

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


    // Try to create the socket connection to port 5005 - if it fails, the site will still work normally
    try {
        // Connect to the dedicated Socket.IO server on port 5005
        const socket = io('http://127.0.0.1:5005');

        // Connection status logging
        socket.on('connect', function () {
            console.log('Socket.IO connected');
        });

        socket.on('disconnect', function () {
            console.log('Socket.IO disconnected');
        });

        // Listen for periodically emitted watch data
        socket.on('watch_update', function (watch) {
            console.log(`Watch update ${watch.uuid}`);

            const $watchRow = $('tr[data-watch-uuid="' + watch.uuid + '"]');
            if ($watchRow.length) {
                $($watchRow).toggleClass('checking-now', watch.checking_now);
                $($watchRow).toggleClass('queued', watch.queued);
                $($watchRow).toggleClass('unviewed', watch.unviewed);
                $($watchRow).toggleClass('error', watch.has_error);
                $($watchRow).toggleClass('notification_muted', watch.notification_muted);
                $($watchRow).toggleClass('paused', watch.paused);

                $('td.last-changed', $watchRow).text(watch.last_checked_text)
                $('td.last-checked .innertext', $watchRow).text(watch.last_checked_text)
                $('td.last-checked', $watchRow).data('timestamp', watch.last_checked).data('fetchduration', watch.fetch_time);
                $('td.last-checked', $watchRow).data('eta_complete', watch.last_checked + watch.fetch_time);

            }
        });

    } catch (e) {
        // If Socket.IO fails to initialize, just log it and continue
        console.log('Socket.IO initialization error:', e);
    }
});