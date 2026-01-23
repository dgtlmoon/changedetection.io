/**
 * Slack Webhook Test Handler
 *
 * Handles testing Slack webhook URLs for tag configurations.
 */
$(document).ready(function () {
    'use strict';

    var $testButton = $('#test-slack-webhook');
    var $testResult = $('#slack-test-result');
    var $testMessage = $('#slack-test-message');
    var $spinner = $testButton.find('.spinner');
    var $webhookInput = $('#slack_webhook_url');

    if (!$testButton.length) {
        return;
    }

    $testButton.on('click', function (e) {
        e.preventDefault();

        var webhookUrl = $webhookInput.val().trim();

        // Validate webhook URL is provided
        if (!webhookUrl) {
            showResult('error', 'Please enter a Slack webhook URL first.');
            return;
        }

        // Basic format validation
        if (!webhookUrl.startsWith('https://hooks.slack.com/services/')) {
            showResult('error', 'Invalid webhook URL format. Expected: https://hooks.slack.com/services/T.../B.../...');
            return;
        }

        // Show loading state
        $testButton.prop('disabled', true);
        $spinner.show();
        $testResult.hide();

        // Send test request
        $.ajax({
            type: 'POST',
            url: slack_webhook_test_url,
            data: {
                slack_webhook_url: webhookUrl
            },
            dataType: 'json'
        })
        .done(function (response) {
            if (response.success) {
                showResult('success', response.message || 'Test message sent successfully!');
            } else {
                showResult('error', response.message || 'Failed to send test message.');
            }
        })
        .fail(function (jqXHR, textStatus, errorThrown) {
            var errorMessage = 'Failed to send test message.';

            if (jqXHR.responseJSON && jqXHR.responseJSON.message) {
                errorMessage = jqXHR.responseJSON.message;
            } else if (jqXHR.status === 0) {
                errorMessage = 'Connection refused or server unreachable.';
            } else if (jqXHR.status === 400) {
                errorMessage = jqXHR.responseText || 'Invalid request.';
            } else if (jqXHR.status === 500) {
                errorMessage = 'Server error occurred.';
            }

            showResult('error', errorMessage);
        })
        .always(function () {
            $testButton.prop('disabled', false);
            $spinner.hide();
        });
    });

    /**
     * Display test result message
     * @param {string} type - 'success' or 'error'
     * @param {string} message - Message to display
     */
    function showResult(type, message) {
        $testResult
            .removeClass('success error')
            .addClass(type)
            .show();
        $testMessage.text(message);
    }
});
