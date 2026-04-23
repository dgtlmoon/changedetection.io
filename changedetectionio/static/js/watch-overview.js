$(function () {
    function normalizeUrl(el) {
        const val = el.value.trim();
        if (val && !/^[a-zA-Z][a-zA-Z\d+\-.]*:/.test(val)) {
            el.value = 'https://' + val;
        }
    }

    $('#url').on('blur keydown', function (e) {
        if (e.type === 'blur' || e.key === 'Enter') {
            normalizeUrl(this);
        }
    });

    $('form').on('submit', function () {
        normalizeUrl($('#url')[0]);
    });

    // Remove unviewed status when normally clicked
    $('.diff-link').click(function () {
        $(this).closest('.unviewed').removeClass('unviewed');
    });

    $('td[data-timestamp]').each(function () {
        $(this).prop('title', new Intl.DateTimeFormat(undefined,
            {
                dateStyle: 'full',
                timeStyle: 'long'
            }).format($(this).data('timestamp') * 1000));
    })

    $("#checkbox-assign-tag").click(function (e) {
        $('#op_extradata').val(prompt("Enter a tag name"));
    });


    $('.history-link').click(function (e) {
        // Incase they click 'back' in the browser, it should be removed.
        $(this).closest('tr').removeClass('unviewed');
    });

    $('.with-share-link > *').click(function () {
        $("#copied-clipboard").remove();

        var range = document.createRange();
        var n = $("#share-link")[0];
        range.selectNode(n);
        window.getSelection().removeAllRanges();
        window.getSelection().addRange(range);
        document.execCommand("copy");
        window.getSelection().removeAllRanges();

        $('.with-share-link').append('<span style="font-size: 80%; color: #fff;" id="copied-clipboard">Copied to clipboard</span>');
        $("#copied-clipboard").fadeOut(2500, function () {
            $(this).remove();
        });
    });

    $(".watch-table tr").click(function (event) {
        var tagName = event.target.tagName.toLowerCase();
        if (tagName === 'tr' || tagName === 'td') {
            var x = $('input[type=checkbox]', this);
            if (x) {
                $(x).click();
            }
        }
    });

    // checkboxes - check all
    $("#check-all").click(function (e) {
        $('input[type=checkbox]').not(this).prop('checked', this.checked);
    });

    const time_check_step_size_seconds=1;

    // checkboxes - show/hide buttons
    $("input[type=checkbox]").click(function (e) {
        if ($('input[type=checkbox]:checked').length) {
            $('#checkbox-operations').slideDown();
        } else {
            $('#checkbox-operations').slideUp();
        }
    });

    setInterval(function () {
        // Background ETA completion for 'checking now'
        $(".watch-table .checking-now .last-checked").each(function () {
            const eta_complete = parseFloat($(this).data('eta_complete'));
            const fetch_duration = parseInt($(this).data('fetchduration'));

            if (eta_complete + 2 > nowtimeserver && fetch_duration > 3) {
                const remaining_seconds = Math.abs(eta_complete) - nowtimeserver - 1;

                let r = Math.round((1.0 - (remaining_seconds / fetch_duration)) * 100);
                if (r < 10) {
                    r = 10;
                }
                if (r >= 90) {
                    r = 100;
                }
                $(this).css('background-size', `${r}% 100%`);
            } else {
                // Snap to full complete
                $(this).css('background-size', `100% 100%`);
            }
        });

        nowtimeserver = nowtimeserver + time_check_step_size_seconds;
    }, time_check_step_size_seconds * 1000);

    // LLM / AI features — only active when the server has LLM configured
    if ($('body').hasClass('llm-configured')) {
        var i18n = window.watchOverviewI18n || {};
        var msgGenerating = i18n.generatingSummary || 'Generating summary…';
        var msgHistory    = i18n.gotoHistory     || 'Goto full history';

        // Reveal intent textarea on first keydown in the quick-add URL field
        var $intentWrap = $('#quick-watch-llm-intent');
        if ($intentWrap.length) {
            $('#new-watch-form input[name="url"]').one('keydown', function () {
                $intentWrap.slideDown(200);
            });
        }

        // Inline AI summary — clicking the Summary button inserts a row below with AJAX content
        $(document).on('click', '.ai-history-btn', function (e) {
            if ($('html').attr('data-ai-mode') !== 'true') return; // normal navigation when AI mode is off

            e.preventDefault();

            var $btn   = $(this);
            var uuid   = $btn.data('uuid');
            var url    = $btn.data('summary-url');
            var $row   = $btn.closest('tr');
            var rowId  = 'ai-summary-row-' + uuid;
            var cols   = $row.find('td').length;
            var $tbody = $row.closest('tbody');

            // Toggle: remove existing row if already open
            if ($('#' + rowId).length) {
                $('#' + rowId).remove();
                $tbody.find('tr:not(.ai-inline-summary-row) td').css('background-color', '');
                return;
            }

            // Snapshot row backgrounds BEFORE DOM mutation — inserting a <tr> shifts nth-child parity
            var $dataRows = $tbody.find('tr:not(.ai-inline-summary-row)');
            var bgMap = [];
            $dataRows.each(function () {
                bgMap.push($(this).find('td:first').css('background-color'));
            });

            var $summaryRow = $(
                '<tr class="ai-inline-summary-row" id="' + rowId + '">' +
                '<td colspan="' + cols + '">' +
                '<div class="ai-inline-summary-content">' +
                '<span class="ai-inline-spinner">&#x2728;</span>' +
                '<div class="ai-inline-body">' +
                '<span class="ai-inline-text">' + $('<span>').text(msgGenerating).html() + '</span>' +
                '</div>' +
                '</div>' +
                '</td></tr>'
            );
            $row.after($summaryRow);

            // Re-apply frozen backgrounds so the nth-child parity shift is invisible
            $dataRows.each(function (i) {
                $(this).find('td').css('background-color', bgMap[i]);
            });

            function formatSummary(text) {
                var sectionRe = /^(Added|Changed|Removed|Updated|New|Deleted)\s*:/i;
                return text.split('\n').map(function (line) {
                    var safe = $('<span>').text(line).html();
                    return sectionRe.test(line.trim())
                        ? safe.replace(/^(\w[\w\s]*)(\s*:)/i, '<strong>$1$2</strong>')
                        : safe;
                }).join('<br>');
            }

            $.getJSON(url)
                .done(function (data) {
                    var $content = $summaryRow.find('.ai-inline-summary-content');
                    var historyUrl = $btn.attr('href');
                    if (data.summary) {
                        $content.addClass('loaded');
                        $content.find('.ai-inline-text').html(formatSummary(data.summary));
                        $content.find('.ai-inline-body').append(
                            '<a href="' + historyUrl + '" class="ai-inline-history-link">' +
                            $('<span>').text(msgHistory).html() + '</a>'
                        );
                    } else if (data.error) {
                        $summaryRow.find('td').html(
                            '<span class="ai-inline-error">' + $('<span>').text(data.error).html() + '</span>'
                        );
                    } else {
                        $summaryRow.remove();
                    }
                })
                .fail(function (xhr) {
                    var msg = (xhr.responseJSON && xhr.responseJSON.error)
                        ? xhr.responseJSON.error
                        : 'AI summary request failed (HTTP ' + xhr.status + ').';
                    $summaryRow.find('td').html(
                        '<span class="ai-inline-error">' + $('<span>').text(msg).html() + '</span>'
                    );
                });
        });
    }
});

