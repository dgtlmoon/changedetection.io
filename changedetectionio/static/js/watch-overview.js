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

    // Bulk "Browser" / "Proxy" actions: open a modal with the same radio choices as the
    // edit page, then set #op_extradata and fire the (hidden) real operation button so the
    // existing socket.io / form submit path applies the choice to the selected watches.
    // Title / button text come from the button's data-* attributes so they pass through
    // server-side i18n (the static JS can't call gettext itself).
    function showBulkChoiceModal($btn, templateId, radioName, hiddenBtnId) {
        const tmpl = document.getElementById(templateId);
        if (!tmpl || typeof ModalDialog === 'undefined') {
            return;
        }
        ModalDialog.confirm({
            type: 'info',
            title: $btn.data('modal-title'),
            message: '<div class="bulk-choice-list">' + tmpl.innerHTML + '</div>',
            confirmText: $btn.data('modal-apply'),
            onConfirm: function () {
                const checked = document.querySelector('.modal-dialog input[name="' + radioName + '"]:checked');
                $('#op_extradata').val(checked ? checked.value : '');
                $('#' + hiddenBtnId).trigger('click');
                // Feedback is server-driven: the backend emits a 'toast' event with the real
                // count/result, handled in realtime.js (and the form fallback flashes on redirect).
            }
        });
    }

    $("#checkbox-set-browser").click(function (e) {
        showBulkChoiceModal($(this), 'bulk-browser-options', 'bulk-fetch-backend', 'op-set-fetch-backend');
    });

    $("#checkbox-set-proxy").click(function (e) {
        showBulkChoiceModal($(this), 'bulk-proxy-options', 'bulk-proxy', 'op-set-proxy');
    });


    $('.history-link').click(function (e) {
        // Incase they click 'back' in the browser, it should be removed.
        $(this).closest('tr').removeClass('unviewed');
    });

    // Inline restock price/stock graph: for restock_diff rows the History button rolls down a
    // price/stock graph (no LLM needed), styled like the AI summary roll-down. Registered before
    // the LLM handler and stops propagation so AI mode never turns these into LLM summaries.
    $(document).on('click', 'tr.processor-restock_diff .ai-history-btn', function (e) {
        e.preventDefault();
        e.stopImmediatePropagation();

        var i18n       = window.watchOverviewI18n || {};
        var $btn       = $(this);
        var uuid       = $btn.data('uuid');
        var dataUrl    = $btn.data('processor-data-url');
        var historyUrl = $btn.attr('href');
        var $row       = $btn.closest('tr');
        var rowId      = 'restock-graph-row-' + uuid;
        var cols       = $row.find('td').length;
        var $tbody     = $row.closest('tbody');

        $row.removeClass('unviewed');

        // Toggle off if already open
        if ($('#' + rowId).length) {
            $('#' + rowId).remove();
            $tbody.find('tr:not(.restock-inline-row) td').css('background-color', '');
            return;
        }

        // Freeze row backgrounds so inserting a <tr> doesn't shift nth-child striping
        var $dataRows = $tbody.find('tr:not(.restock-inline-row)');
        var bgMap = [];
        $dataRows.each(function () { bgMap.push($(this).find('td:first').css('background-color')); });

        var $r = $(
            '<tr class="restock-inline-row" id="' + rowId + '">' +
            '<td colspan="' + cols + '">' +
            '<div class="restock-inline-graph"></div>' +
            '<a class="restock-inline-history-link"></a>' +
            '</td></tr>'
        );
        $r.find('.restock-inline-graph').text(i18n.loadingPriceHistory || 'Loading price history…');
        $r.find('.restock-inline-history-link').attr('href', historyUrl).text(i18n.gotoHistory || 'Goto full history');
        $row.after($r);

        // Re-apply frozen backgrounds so the nth-child parity shift is invisible
        $dataRows.each(function (i) { $(this).find('td').css('background-color', bgMap[i]); });

        function showError() {
            $r.find('.restock-inline-graph').html(
                '<span class="restock-inline-error">' +
                $('<span>').text(i18n.priceHistoryError || 'Could not load price history.').html() +
                '</span>'
            );
        }

        if (!dataUrl) { showError(); return; }

        $.getJSON(dataUrl).done(function (data) {
            var series = (data && data.series) || [];
            var graphI18n = {
                in_stock: i18n.inStock, out_of_stock: i18n.outOfStock,
                no_data: i18n.noPriceData, load_error: i18n.priceHistoryError,
                changes: i18n.changes, avg_price: i18n.avgPrice,
                price_low: i18n.priceLow, price_typical: i18n.priceTypical, price_high: i18n.priceHigh,
                cheaper_than: i18n.cheaperThan, pricier_than: i18n.pricierThan,
                typical_note: i18n.typicalNote, avg_label: i18n.avgLabel
            };
            if (window.renderRestockGraph) {
                window.renderRestockGraph($r.find('.restock-inline-graph')[0], series, (data && data.currency) || '', graphI18n, (data && data.summary) || null);
            }
        }).fail(showError);
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
            var cb = $('input[type=checkbox]', this)[0];
            if (cb) {
                // Forward the shiftKey so shift-clicking anywhere on a row does a
                // range-select (a plain $(cb).click() would drop the modifier).
                cb.dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: event.shiftKey }));
            }
        }
    });

    // ---- Cross-page selection store -------------------------------------------
    // Selection is a Set of watch UUIDs (the source of truth) rather than the DOM,
    // so it spans paginated pages. Persisted in sessionStorage scoped to the
    // watch-list page + the active tag (only): a selection survives switching the
    // status/processor/search/pagination views, but each tag group (and the
    // untagged "all" view) gets its own selection bucket. The "/uuids" endpoint
    // supplies the full matching id list for "select all matching".
    const sel = window.cdioWatchSelection = (function () {
        const KEY = 'cdio-watch-selection';
        function scopeKey() {
            const tag = new URLSearchParams(location.search).get('tag') || '';
            return location.pathname + (tag ? '?tag=' + tag : '');
        }
        let uuids = new Set();
        try {
            const obj = JSON.parse(sessionStorage.getItem(KEY) || 'null');
            if (obj && obj.scope === scopeKey() && Array.isArray(obj.uuids)) {
                uuids = new Set(obj.uuids);
            }
        } catch (e) { /* private mode / corrupt — best effort */ }
        function persist() {
            try {
                sessionStorage.setItem(KEY, JSON.stringify({ scope: scopeKey(), uuids: Array.from(uuids) }));
            } catch (e) { /* quota / private mode */ }
        }
        return {
            has: (u) => uuids.has(u),
            add: (u) => { uuids.add(u); persist(); },
            remove: (u) => { uuids.delete(u); persist(); },
            toggle: (u) => { if (uuids.has(u)) { uuids.delete(u); } else { uuids.add(u); } persist(); },
            addMany: (arr) => { arr.forEach((u) => uuids.add(u)); persist(); },
            clear: () => { uuids.clear(); persist(); },
            all: () => Array.from(uuids),
            size: () => uuids.size
        };
    })();

    const selCfg = window.watchListSelection || {};
    const totalMatching = parseInt(selCfg.total, 10) || 0;

    // Row checkbox values carry a trailing space in the template — always trim.
    const cbUuid = (el) => (el.value || '').trim();
    const $rowCbs = () => $('input[name="uuids"][type=checkbox]');
    const fmtNum = (n) => new Intl.NumberFormat(navigator.language).format(n);

    // Reflect the store onto this page's checkboxes (load + after bulk changes).
    function applySelectionToDom() {
        $rowCbs().each(function () { this.checked = sel.has(cbUuid(this)); });
        const visible = $rowCbs().get();
        $('#check-all').prop('checked', visible.length > 0 && visible.every((el) => el.checked));
    }

    function updateRecordsSelected() {
        const $el = $('#records-selected');
        if (!$el.length) return;
        const n = sel.size();
        if (n > 0) {
            const tpl = $el.attr('data-template') || '%(count)s records selected';
            // Only the count is emphasised; the number is locale-formatted digits.
            $el.html(tpl.replace('%(count)s', '<strong>' + fmtNum(n) + '</strong>')).show();
        } else {
            $el.hide();
        }
    }

    function updateSelectAllBanner() {
        const $b = $('#select-all-banner');
        if (!$b.length) return;
        const visible = $rowCbs().map(function () { return cbUuid(this); }).get();
        const allVisibleSelected = visible.length > 0 && visible.every((u) => sel.has(u));

        if (allVisibleSelected && totalMatching > 0 && sel.size() >= totalMatching) {
            const tpl = $b.attr('data-all-selected-tmpl') || 'All %(total)s matching are selected.';
            $b.html(
                tpl.replace('%(total)s', '<strong>' + fmtNum(totalMatching) + '</strong>') +
                ' <button type="button" class="pure-button button-xsmall" id="select-all-clear">' +
                ($b.attr('data-clear-action') || 'Clear selection') + '</button>'
            ).show();
        } else if (allVisibleSelected && totalMatching > visible.length) {
            const tpl = $b.attr('data-select-all-tmpl') || 'All %(page)s on this page are selected.';
            const action = ($b.attr('data-select-all-action') || 'Select all %(total)s matching')
                .replace('%(total)s', fmtNum(totalMatching));
            $b.html(
                tpl.replace('%(page)s', '<strong>' + fmtNum(visible.length) + '</strong>') +
                ' <button type="button" class="pure-button button-xsmall" id="select-all-matching">' + action + '</button>'
            ).show();
        } else {
            $b.hide().empty();
        }
    }

    function refreshSelectionUI() {
        // Toggle a single body class - everything (operations bar visibility, hiding the whole-list
        // buttons) is driven off body.watch-selection-active in CSS (see _watch_table.scss).
        // No jQuery slideUp/slideDown.
        // Base it on a checkbox actually being checked on THIS page, not sel.size(): the store is a
        // cross-page set persisted in sessionStorage, so a leftover/off-page selection would
        // otherwise light up the class with nothing visibly selected.
        const anyVisibleChecked = $rowCbs().get().some((el) => el.checked);
        $('body').toggleClass('watch-selection-active', anyVisibleChecked);
        updateRecordsSelected();
        updateSelectAllBanner();
    }
    // Exposed so realtime.js can refresh the UI after it mutates the selection
    // (e.g. clearing it once a delete operation removes the rows).
    sel.refreshUI = refreshSelectionUI;

    // Shift-click to (de)select a contiguous range, anchored on the last checkbox
    // clicked — the usual "select many at once" gesture. Runs on 'click' (which
    // carries shiftKey) before the 'change' handler below.
    let lastCheckedIndex = null;
    $(document).on('click', 'input[name="uuids"][type=checkbox]', function (e) {
        const boxes = $rowCbs().get();
        const idx = boxes.indexOf(this);
        if (e.shiftKey && lastCheckedIndex !== null && lastCheckedIndex < boxes.length) {
            const lo = Math.min(idx, lastCheckedIndex);
            const hi = Math.max(idx, lastCheckedIndex);
            for (let i = lo; i <= hi; i++) {
                boxes[i].checked = this.checked;
                if (this.checked) { sel.add(cbUuid(boxes[i])); } else { sel.remove(cbUuid(boxes[i])); }
            }
            refreshSelectionUI();
        }
        lastCheckedIndex = idx;
    });

    // Individual row checkbox toggled (direct click, or via the row-click handler).
    $(document).on('change', 'input[name="uuids"][type=checkbox]', function () {
        if (this.checked) { sel.add(cbUuid(this)); } else { sel.remove(cbUuid(this)); }
        const visible = $rowCbs().get();
        $('#check-all').prop('checked', visible.length > 0 && visible.every((el) => el.checked));
        refreshSelectionUI();
    });

    // Check-all (this page only).
    $("#check-all").click(function () {
        const on = this.checked;
        $rowCbs().each(function () {
            this.checked = on;
            if (on) { sel.add(cbUuid(this)); } else { sel.remove(cbUuid(this)); }
        });
        refreshSelectionUI();
    });

    // Invert this page's selection.
    $("#check-invert").click(function () {
        $rowCbs().each(function () { sel.toggle(cbUuid(this)); });
        applySelectionToDom();
        refreshSelectionUI();
    });

    // Cancel: clear the whole cross-page selection (incl. the stored browser data)
    // and dismiss the operations bar.
    $("#check-cancel").click(function () {
        sel.clear();
        applySelectionToDom();
        refreshSelectionUI();
    });

    // "Select all N matching" — pull the full matching id list from the server.
    $(document).on('click', '#select-all-matching', function () {
        if (!selCfg.uuidsUrl) return;
        const $btn = $(this).prop('disabled', true);
        $.getJSON(selCfg.uuidsUrl + location.search)
            .done(function (data) {
                if (data && Array.isArray(data.uuids)) {
                    sel.addMany(data.uuids.map((u) => ('' + u).trim()));
                    applySelectionToDom();
                    refreshSelectionUI();
                }
            })
            .always(function () { $btn.prop('disabled', false); });
    });

    // "Clear selection" link inside the banner.
    $(document).on('click', '#select-all-clear', function () {
        sel.clear();
        applySelectionToDom();
        refreshSelectionUI();
    });

    const time_check_step_size_seconds=1;

    // On load: reflect any persisted selection onto this page, then refresh the UI.
    applySelectionToDom();
    refreshSelectionUI();

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
        var msgGenerating = i18n.generatingSummary || 'Generating change summary…';
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
            // restock_diff rows have their own graph roll-down handler (above) - never LLM here.
            if ($(this).closest('tr').hasClass('processor-restock_diff')) return;
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

            var promptUrl = url + '/prompt';

            // Fire both requests simultaneously — prompt returns immediately, summary after LLM
            $.getJSON(promptUrl)
                .done(function (data) {
                    if (data.prompt && $summaryRow.find('.ai-inline-summary-content:not(.loaded)').length) {
                        $summaryRow.find('.ai-inline-body').append(
                            '<span class="ai-inline-prompt">' + $('<span>').text(data.prompt).html() + '</span>'
                        );
                    }
                });

            $.getJSON(url)
                .done(function (data) {
                    var $content = $summaryRow.find('.ai-inline-summary-content');
                    var historyUrl = $btn.attr('href');
                    if (data.summary) {
                        $content.addClass('loaded');
                        $content.find('.ai-inline-text').html(formatSummary(data.summary));
                        $content.find('.ai-inline-prompt').remove();
                    } else if (data.error) {
                        $summaryRow.find('td').html(
                            '<span class="ai-inline-error">' + $('<span>').text(data.error).html() + '</span>'
                        );
                    }
                    $content.find('.ai-inline-body').append(
                        '<a href="' + historyUrl + '" class="ai-inline-history-link">' +
                        $('<span>').text(msgHistory).html() + '</a>'
                    );

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

