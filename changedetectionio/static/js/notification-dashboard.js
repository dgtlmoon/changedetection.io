/**
 * Notification Dashboard - Interactive functionality
 * Handles timezone conversion, AJAX log fetching, and user interactions
 */

$(function() {
    // Convert retry timestamps to local timezone
    $('.retry-time[data-timestamp]').each(function() {
        var timestamp = parseInt($(this).data('timestamp'));
        if (timestamp) {
            var formatted = new Intl.DateTimeFormat(undefined, {
                year: 'numeric', month: '2-digit', day: '2-digit',
                hour: '2-digit', minute: '2-digit', second: '2-digit',
                timeZoneName: 'short'
            }).format(timestamp * 1000);
            $(this).text(formatted);
        }
    });

    // Handle notification card clicks to fetch and display logs
    $('.notification-card').css('cursor', 'pointer').click(function(e) {
        // Don't trigger if clicking on a button or form
        if ($(e.target).is('button, input') || $(e.target).closest('form, button').length) return;

        var taskId = $(this).data('task-id');
        if (!taskId) return;

        // Show loading state
        $('#last-log-info').show();
        $('#log-apprise-content').text('Loading...');

        // Fetch log via AJAX
        var logUrl = $('#log-url-template').data('url').replace('TASK_ID', taskId);
        $.getJSON(logUrl)
            .done(function(data) {
                $('#log-task-id').text(data.task_id);
                $('#log-watch-url').text(data.watch_url || '').parent().toggle(!!data.watch_url);

                if (data.notification_urls && data.notification_urls.length) {
                    $('#log-notification-urls').html(data.notification_urls.map(url =>
                        '<div class="endpoint-item">• ' + url + '</div>').join(''));
                    $('#log-notification-urls-container').show();
                } else {
                    $('#log-notification-urls-container').hide();
                }

                $('#log-apprise-content').text(data.apprise_log || 'No log available');
                $('#log-error-content').text(data.error || '');
                $('#log-error-container').toggle(!!data.error);

                // Scroll to log
                $('#last-log-info')[0].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            })
            .fail(function(xhr) {
                var error = xhr.responseJSON && xhr.responseJSON.error ? xhr.responseJSON.error : 'Failed to load log';
                $('#log-apprise-content').text('Error: ' + error);
            });
    });
});
