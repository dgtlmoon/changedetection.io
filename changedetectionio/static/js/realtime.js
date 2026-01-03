// Socket.IO client-side integration for changedetection.io

$(document).ready(function () {

    function reapplyTableStripes() {
        $('.watch-table tbody tr').each(function(index) {
            $(this).removeClass('pure-table-odd pure-table-even');
            $(this).addClass(index % 2 === 0 ? 'pure-table-odd' : 'pure-table-even');
        });
    }

    function bindSocketHandlerButtonsEvents(socket) {
        $('.ajax-op').on('click.socketHandlerNamespace', function (e) {
            e.preventDefault();
            const op = $(this).data('op');
            const uuid = $(this).closest('tr').data('watch-uuid');
            
            console.log(`Socket.IO: Sending watch operation '${op}' for UUID ${uuid}`);
            
            // Emit the operation via Socket.IO
            socket.emit('watch_operation', {
                'op': op,
                'uuid': uuid
            });
            
            return false;
        });


        $('#checkbox-operations button').on('click.socketHandlerNamespace', function (e) {
            e.preventDefault();
            const $button = $(this);
            const op = $button.val();
            const checkedUuids = $('input[name="uuids"]:checked').map(function () {
                return this.value.trim();
            }).get();

            // Check if this button requires confirmation
            console.log('Button clicked, op:', op, 'requires-confirm:', $button.is('[data-requires-confirm]'));
            if ($button.is('[data-requires-confirm]')) {
                console.log('Showing modal confirmation for operation:', op);
                const config = {
                    type: $button.data('confirm-type') || 'danger',
                    title: $button.data('confirm-title') || 'Confirm Action',
                    message: $button.data('confirm-message') || '<p>Are you sure you want to proceed?</p>',
                    confirmText: $button.data('confirm-button') || 'Confirm',
                    cancelText: $button.data('cancel-button') || 'Cancel',
                    onConfirm: function() {
                        console.log(`Socket.IO: Sending watch operation '${op}' for UUIDs:`, checkedUuids);
                        socket.emit('checkbox-operation', {
                            op: op,
                            uuids: checkedUuids,
                            extra_data: $('#op_extradata').val()
                        });
                        $('input[name="uuids"]:checked').prop('checked', false);
                        $('#check-all:checked').prop('checked', false);
                    }
                };
                ModalDialog.confirm(config);
            } else {
                console.log(`Socket.IO: Sending watch operation '${op}' for UUIDs:`, checkedUuids);
                socket.emit('checkbox-operation', {
                    op: op,
                    uuids: checkedUuids,
                    extra_data: $('#op_extradata').val()
                });
                $('input[name="uuids"]:checked').prop('checked', false);
                $('#check-all:checked').prop('checked', false);
            }

            return false;
        });

    }


    // Cache DOM elements for performance
    const queueBubble = document.getElementById('queue-bubble');

    // Only try to connect if authentication isn't required or user is authenticated
    // The 'is_authenticated' variable will be set in the template
    if (typeof is_authenticated !== 'undefined' ? is_authenticated : true) {
        // Try to create the socket connection to the SocketIO server - if it fails, the site will still work normally
        try {
            // Connect to Socket.IO on the same host/port, with path from template
            const socket = io({
                path: socketio_url,  // This will be the path prefix like "/app/socket.io" from the template
                transports: ['websocket', 'polling'],
                reconnectionDelay: 3000,
                reconnectionAttempts: 25
            });

            // Connection status logging
            socket.on('connect', function () {
                $('#realtime-conn-error').hide();
                console.log('Socket.IO connected with path:', socketio_url);
                console.log('Socket transport:', socket.io.engine.transport.name);
                bindSocketHandlerButtonsEvents(socket);
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
                $('.ajax-op').off('.socketHandlerNamespace');
                $('#realtime-conn-error').show();
            });

            socket.on('queue_size', function (data) {
                console.log(`${data.event_timestamp} - Queue size update: ${data.q_length}`);

                // Update queue bubble in action sidebar
                if (queueBubble) {
                    const count = parseInt(data.q_length) || 0;
                    const oldCount = parseInt(queueBubble.getAttribute('data-count')) || 0;

                    if (count > 0) {
                        // Format number according to browser locale
                        const formatter = new Intl.NumberFormat(navigator.language);
                        queueBubble.textContent = formatter.format(count);
                        queueBubble.setAttribute('data-count', count);
                        queueBubble.classList.add('visible');

                        // Add large-number class for numbers > 999
                        if (count > 999) {
                            queueBubble.classList.add('large-number');
                        } else {
                            queueBubble.classList.remove('large-number');
                        }

                        // Pulse animation if count changed
                        if (count !== oldCount) {
                            queueBubble.classList.remove('pulse');
                            // Force reflow to restart animation
                            void queueBubble.offsetWidth;
                            queueBubble.classList.add('pulse');
                        }
                    } else {
                        // Hide bubble when queue is empty
                        queueBubble.classList.remove('visible', 'pulse', 'large-number');
                        queueBubble.setAttribute('data-count', '0');
                    }
                }
            })

            // Listen for operation results
            socket.on('operation_result', function (data) {
                if (data.success) {
                    console.log(`Socket.IO: Operation '${data.operation}' completed successfully for UUID ${data.uuid}`);
                } else {
                    console.error(`Socket.IO: Operation failed: ${data.error}`);
                    alert("There was a problem processing the request: " + data.error);
                }
            });

            socket.on('watch_small_status_comment', function (data) {
                console.log(`Socket.IO: Operation  watch_small_status_comment'${data.uuid}' status ${data.status}`);
                $('tr[data-watch-uuid="' + data.uuid + '"] td.last-checked .status-text').html("&nbsp;").text(data.status);
            });

            socket.on('notification_event', function (data) {
                console.log(`Stub handler for notification_event ${data.watch_uuid}`)
            });

            socket.on('watch_deleted', function (data) {
                $('tr[data-watch-uuid="' + data.uuid + '"] td').fadeOut(500, function () {
                    $(this).closest('tr').remove();
                    reapplyTableStripes();
                });
            });

            // So that the favicon is only updated when the server has written the scraped favicon to disk.
            socket.on('watch_bumped_favicon', function (watch) {
                const $watchRow = $(`tr[data-watch-uuid="${watch.uuid}"]`);
                if ($watchRow.length) {
                    $watchRow.addClass('has-favicon');
                    // Because the event could be emitted from a process that is outside the app context, url_for() might not work.
                    // Lets use url_for at template generation time to give us a PLACEHOLDER instead
                    let favicon_url = favicon_baseURL.replace('/PLACEHOLDER', `/${watch.uuid}?cache=${watch.event_timestamp}`);
                    console.log(`Setting favicon for UUID - ${watch.uuid} - ${favicon_url}`);
                    $('img.favicon', $watchRow).attr('src', favicon_url);
                }
            })

            socket.on('general_stats_update', function (general_stats) {
                // Tabs at bottom of list
                $('#watch-table-wrapper').toggleClass("has-unread-changes", general_stats.unread_changes_count !==0)
                $('#watch-table-wrapper').toggleClass("has-error", general_stats.count_errors !== 0)
                $('#post-list-with-errors a').text(`With errors (${ new Intl.NumberFormat(navigator.language).format(general_stats.count_errors) })`);
                $('#unread-tab-counter').text(new Intl.NumberFormat(navigator.language).format(general_stats.unread_changes_count));
            });

            socket.on('watch_update', function (data) {
                const watch = data.watch;

                // Updating watch table rows
                const $watchRow = $('tr[data-watch-uuid="' + watch.uuid + '"]');
                console.log('Found watch row elements:', $watchRow.length);

                if ($watchRow.length) {
                    $($watchRow).toggleClass('checking-now', watch.checking_now);
                    $($watchRow).toggleClass('queued', watch.queued);
                    $($watchRow).toggleClass('unviewed', watch.unviewed);
                    $($watchRow).toggleClass('has-error', watch.has_error);
                    $($watchRow).toggleClass('has-favicon', watch.has_favicon);
                    $($watchRow).toggleClass('notification_muted', watch.notification_muted);
                    $($watchRow).toggleClass('paused', watch.paused);
                    $($watchRow).toggleClass('single-history', watch.history_n === 1);
                    $($watchRow).toggleClass('multiple-history', watch.history_n >= 2);

                    $('td.title-col .error-text', $watchRow).html(watch.error_text)
                    $('td.last-changed', $watchRow).text(watch.last_changed_text)
                    $('td.last-checked .innertext', $watchRow).text(watch.last_checked_text)
                    $('td.last-checked', $watchRow).data('timestamp', watch.last_checked).data('fetchduration', watch.fetch_time);
                    $('td.last-checked', $watchRow).data('eta_complete', watch.last_checked + watch.fetch_time);

                    console.log('Updated UI for watch:', watch.uuid);
                }
                $('body').toggleClass('checking-now', watch.checking_now && window.location.href.includes(watch.uuid));
            });

        } catch (e) {
            // If Socket.IO fails to initialize, just log it and continue
            console.log('Socket.IO initialization error:', e);
        }
    }
});