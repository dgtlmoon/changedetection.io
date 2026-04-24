
function request_textpreview_update() {
    if (!$('body').hasClass('preview-text-enabled')) {
        console.error("Preview text was requested but body tag was not setup")
        return
    }

    const data = {};
    $('textarea:visible, input:visible').each(function () {
        const $element = $(this); // Cache the jQuery object for the current element
        const name = $element.attr('name'); // Get the name attribute of the element
        data[name] = $element.is(':checkbox') ? ($element.is(':checked') ? $element.val() : false) : $element.val();
    });

    // llm_intent lives in a separate (potentially hidden) tab — include it explicitly
    const $llmIntent = $('textarea[name="llm_intent"]');
    if ($llmIntent.length) {
        data['llm_intent'] = $llmIntent.val();
    }

    $('body').toggleClass('spinner-active', 1);
    $('#llm-preview-result').hide();

    $.abortiveSingularAjax({
        type: "POST",
        url: preview_text_edit_filters_url,
        data: data,
        namespace: 'watchEdit'
    }).done(function (data) {
        console.debug(data['duration'])
        $('#filters-and-triggers #text-preview-before-inner').text(data['before_filter']);
        $('#filters-and-triggers #text-preview-inner')
            .text(data['after_filter'])
            .highlightLines([
                {
                    'color': 'var(--highlight-trigger-text-bg-color)',
                    'lines': data['trigger_line_numbers'],
                    'title': "Triggers a change if this text appears, AND something changed in the document."
                },
                {
                    'color': 'var(--highlight-ignored-text-bg-color)',
                    'lines': data['ignore_line_numbers'],
                    'title': "Ignored for calculating changes, but still shown."
                },
                {
                    'color': 'var(--highlight-blocked-text-bg-color)',
                    'lines': data['blocked_line_numbers'],
                    'title': "No change-detection will occur because this text exists."
                }
            ])

        // LLM preview extraction result
        const $llmResult = $('#llm-preview-result');
        if ($llmResult.length && data['llm_evaluation']) {
            const ev = data['llm_evaluation'];
            const found = ev['found'];
            $llmResult.attr('data-found', found ? '1' : '0');
            $llmResult.find('.llm-preview-verdict').text(
                found ? '✓ Would trigger a change' : '✗ Would not trigger a change'
            );
            $llmResult.find('.llm-preview-answer').text(ev['answer'] || '');
            $llmResult.show();
        } else if ($llmResult.length) {
            $llmResult.hide();
        }
    }).fail(function (error) {
        if (error.statusText === 'abort') {
            console.log('Request was aborted due to a new request being fired.');
        } else {
            $('#filters-and-triggers #text-preview-inner').text('There was an error communicating with the server.');
        }
    })
}


$(document).ready(function () {

    $('#notification-setting-reset-to-default').click(function (e) {
        $('#notification_title').val('');
        $('#notification_body').val('');
        $('#notification_format').val('System default');
        $('#notification_urls').val('');
        $('#notification_muted_none').prop('checked', true); // in the case of a ternary field
        e.preventDefault();
    });
    $("#notification-token-toggle").click(function (e) {
        e.preventDefault();
        $('#notification-tokens-info').toggle();
    });

    toggleOpacity('#time_between_check_use_default', '#time-check-widget-wrapper, #time-between-check-schedule', false);


    const vh = Math.max(document.documentElement.clientHeight || 0, window.innerHeight || 0);
    $("#text-preview-inner").css('max-height', (vh - 300) + "px");
    $("#text-preview-before-inner").css('max-height', (vh - 300) + "px");

    $("#activate-text-preview").click(function (e) {
        $('body').toggleClass('preview-text-enabled')
        request_textpreview_update();
        const method = $('body').hasClass('preview-text-enabled') ? 'on' : 'off';
        $('#filters-and-triggers textarea')[method]('blur', request_textpreview_update.throttle(1000));
        $('#filters-and-triggers input')[method]('change', request_textpreview_update.throttle(1000));
        $("#filters-and-triggers-tab")[method]('click', request_textpreview_update.throttle(1000));
    });
    $('.minitabs-wrapper').miniTabs({
        "Content after filters": "#text-preview-inner",
        "Content raw/before filters": "#text-preview-before-inner"
    });
});

