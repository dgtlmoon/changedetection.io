// Restock price/stock timeline - a hand-rolled smoothed SVG line graph.
// Line segments are green where the item was in stock and red where it was out of stock.
//
// Two consumers:
//   * the restock diff page (#restock-graph), which fetches window.restock_data_url and also
//     builds the data table below it; and
//   * the watchlist inline roll-down, which calls window.renderRestockGraph(el, series, currency, i18n).
//
// Series shape (oldest -> newest): [{timestamp: <epoch sec>, price: <float|null>, in_stock: <bool|null>}]

(function ($) {
    'use strict';

    const SVG_NS = 'http://www.w3.org/2000/svg';
    const COLOR_IN = '#1fa463';   // in stock = green
    const COLOR_OUT = '#e74c3c';  // out of stock = red
    const COLOR_UNKNOWN = '#999'; // stock state not known
    const HEIGHT = 320;          // default (diff page); the inline watchlist graph passes a shorter one
    const PAD = { top: 20, right: 16, bottom: 30, left: 52 };
    const MAX_X_LABELS = 6;       // keep the date axis uncluttered

    const DEFAULT_I18N = { in_stock: 'In stock', out_of_stock: 'Out of stock',
        no_data: 'No price data available to graph yet.', load_error: 'Could not load price history.',
        changes: 'Number of changes', avg_price: 'average price',
        price_low: 'Currently low', price_typical: 'Currently typical', price_high: 'Currently high',
        cheaper_than: 'cheaper than %s% of tracked prices',
        pricier_than: 'more expensive than %s% of tracked prices',
        typical_note: 'around the usual price', avg_label: 'avg' };
    const OVERLAY_MIN_POINTS = 5; // need enough history for low/typical/high to be meaningful

    function el(name, attrs) {
        const e = document.createElementNS(SVG_NS, name);
        for (const k in attrs) e.setAttribute(k, attrs[k]);
        return e;
    }

    function stockColor(inStock) {
        if (inStock === true) return COLOR_IN;
        if (inStock === false) return COLOR_OUT;
        return COLOR_UNKNOWN;
    }

    // X-axis label: day + short month + short year, e.g. "21 Jun '25".
    function fmtAxisDate(epoch) {
        const d = new Date(epoch * 1000);
        const dm = d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
        return `${dm} '${String(d.getFullYear()).slice(-2)}`;
    }

    function fmtDateTime(epoch) {
        // undefined locale => the browser's locale; explicit options for a clean, complete format.
        return new Date(epoch * 1000).toLocaleString(undefined, {
            year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
        });
    }

    function fmtPrice(v, currency) {
        const n = Math.round(v * 100) / 100;
        return (currency || '') + (Number.isInteger(n) ? n : n.toFixed(2));
    }

    // Thin a large price series down to ~target points for drawing (you can't perceive more
    // points than pixels). Always keeps the first, last and the true min/max points so the line
    // still touches its extremes. The axis range + summary stay computed over the FULL data.
    function downsample(arr, target) {
        if (arr.length <= target) return arr;
        const keep = new Set([0, arr.length - 1]);
        let minI = 0, maxI = 0;
        for (let i = 1; i < arr.length; i++) {
            if (arr[i].price < arr[minI].price) minI = i;
            if (arr[i].price > arr[maxI].price) maxI = i;
        }
        keep.add(minI); keep.add(maxI);
        const step = arr.length / target;
        for (let i = 0; i < target; i++) keep.add(Math.floor(i * step));
        return Array.from(keep).sort((a, b) => a - b).map(i => arr[i]);
    }

    function draw($container, series, currency, i18n, summary, height) {
        height = height || HEIGHT;
        // Only points that actually have a price can sit on the line.
        const data = (series || []).filter(p => p.price !== null && p.price !== undefined);
        if (data.length < 2) {
            $container.html($('<p class="pure-form-message-inline"></p>').text(i18n.no_data));
            return;
        }

        const width = Math.max($container.width() || 0, 320);
        const innerH = height - PAD.top - PAD.bottom;

        const prices = data.map(p => p.price);
        let dataMin = Math.min.apply(null, prices), dataMax = Math.max.apply(null, prices);
        if (dataMin === dataMax) { dataMin -= 1; dataMax += 1; }
        // Pad the value domain ~10% top & bottom so the (smoothed, possibly overshooting) line
        // and the min/max labels sit inside the plot area instead of being clipped at the edges.
        const vpad = (dataMax - dataMin) * 0.1;
        const domMin = dataMin - vpad, domMax = dataMax + vpad, range = domMax - domMin;

        const ticks = [dataMax, (dataMin + dataMax) / 2, dataMin];

        // Widen the left gutter to fit the price labels (e.g. "CZK12.34") so a long currency
        // prefix isn't clipped at the SVG's left edge. ~7px/char + padding.
        const maxLabelChars = Math.max.apply(null, ticks.map(v => fmtPrice(v, currency).length));
        const padLeft = Math.max(PAD.left, maxLabelChars * 7 + 14);

        const innerW = width - padLeft - PAD.right;
        // Draw at most ~one point per few pixels; keeps the SVG light on long histories / mobile.
        const drawData = downsample(data, Math.max(40, Math.min(250, Math.floor(innerW / 4))));
        const x = i => padLeft + (i * innerW) / (drawData.length - 1);
        const y = price => PAD.top + (1 - (price - domMin) / range) * innerH;
        const pts = drawData.map((p, i) => ({ x: x(i), y: y(p.price), d: p }));

        // Size the SVG in real pixels at the measured width (no viewBox => no CSS rescaling).
        const svg = el("svg", { width: width, height: height, role: "img" });

        // Y axis: max / mid / min gridlines + price labels.
        ticks.forEach(price => {
            const yy = y(price);
            svg.appendChild(el('line', { class: 'rg-axis', x1: padLeft, y1: yy, x2: width - PAD.right, y2: yy, opacity: price === dataMin ? 0.6 : 0.15 }));
            const t = el('text', { class: 'rg-label', x: padLeft - 8, y: yy + 4, 'text-anchor': 'end' });
            t.textContent = fmtPrice(price, currency);
            svg.appendChild(t);
        });

        // Analyser overlays (Google-Flights style): a "typical range" band (p25-p75) behind the
        // line + a dashed average line. Drawn before the data line so they sit behind it.
        const showOverlays = summary && summary.count >= OVERLAY_MIN_POINTS;
        if (showOverlays) {
            const yTop = y(summary.p75), yBot = y(summary.p25);
            svg.appendChild(el('rect', {
                class: 'rg-band', x: padLeft, y: Math.min(yTop, yBot),
                width: Math.max(0, width - PAD.right - padLeft), height: Math.abs(yBot - yTop)
            }));
            const yAvg = y(summary.avg);
            svg.appendChild(el('line', {
                class: 'rg-avg-line', x1: padLeft, y1: yAvg, x2: width - PAD.right, y2: yAvg,
                'stroke-dasharray': '4 4'
            }));
            const at = el('text', { class: 'rg-label rg-avg-text', x: width - PAD.right, y: yAvg - 4, 'text-anchor': 'end' });
            at.textContent = i18n.avg_label || 'avg';
            svg.appendChild(at);
        }

        // Single neutral straight-line path connecting the points (no smoothing — a curve
        // overshoots and reads as a price move that didn't happen). Stock status is shown by the
        // DOT colours instead, not the line.
        let linePath = '';
        pts.forEach((p, i) => { linePath += (i === 0 ? 'M ' : ' L ') + p.x.toFixed(1) + ' ' + p.y.toFixed(1); });
        svg.appendChild(el('path', {
            class: 'rg-line', d: linePath, fill: 'none',
            'stroke-width': 2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round'
        }));

        // Dots, coloured by each point's own stock state (green = in stock, red = out of stock).
        pts.forEach(p => {
            svg.appendChild(el('circle', { cx: p.x.toFixed(1), cy: p.y.toFixed(1), r: 3.2, fill: stockColor(p.d.in_stock) }));
        });

        // Sparse x-axis date labels: evenly spaced, always including both endpoints. The number
        // adapts to the available width (each label ~64px) so they don't jam together on narrow
        // / mobile widths, capped at MAX_X_LABELS on desktop. Min 2 (the two endpoints).
        const fitLabels = Math.max(2, Math.min(MAX_X_LABELS, Math.floor(innerW / 64)));
        const count = Math.min(fitLabels, pts.length);
        const labelIdx = Array.from(new Set(
            Array.from({ length: count }, (_, i) => Math.round((i * (pts.length - 1)) / (count - 1)))
        ));
        labelIdx.forEach(i => {
            const anchor = i === 0 ? 'start' : (i === pts.length - 1 ? 'end' : 'middle');
            const t = el('text', { class: 'rg-label', x: pts[i].x.toFixed(1), y: height - 10, 'text-anchor': anchor });
            t.textContent = fmtAxisDate(pts[i].d.timestamp);
            svg.appendChild(t);
        });

        $container.empty().append(svg);

        // --- Hover tooltip: a generous transparent hit-circle per point shows price + date ---
        const $tip = $('<div class="rg-tooltip"></div>').appendTo($container);
        pts.forEach(p => {
            const state = p.d.in_stock === null ? '' :
                (p.d.in_stock ? ' &middot; ' + i18n.in_stock : ' &middot; ' + i18n.out_of_stock);
            const hit = el('circle', { cx: p.x.toFixed(1), cy: p.y.toFixed(1), r: 14, fill: 'transparent', style: 'cursor: pointer;' });
            svg.appendChild(hit);
            $(hit).on('mouseenter mousemove', function (e) {
                const r = $container[0].getBoundingClientRect();
                const cx = e.clientX - r.left, cy = e.clientY - r.top;
                $tip.html('<strong>' + fmtPrice(p.d.price, currency) + '</strong>' + state + '<br>' + fmtDateTime(p.d.timestamp)).show();
                const tipW = $tip.outerWidth(), GAP = 14;
                // Default to the right of the cursor; flip left if it would overflow the right edge.
                let left = cx + GAP;
                if (left + tipW > $container.width()) left = cx - GAP - tipW;
                if (left < 0) left = 0;
                $tip.css({ left: left + 'px', top: cy + 'px' });
            }).on('mouseleave', function () {
                $tip.hide();
            });
        });

        // Legend explaining the dot colours (the line is neutral; only dots indicate stock).
        const $legend = $('<div class="rg-legend"></div>');
        $legend.append($('<span class="rg-legend-item"></span>')
            .append('<span class="rg-legend-dot in"></span>').append(document.createTextNode(' ' + (i18n.in_stock || 'In stock'))));
        $legend.append($('<span class="rg-legend-item"></span>')
            .append('<span class="rg-legend-dot out"></span>').append(document.createTextNode(' ' + (i18n.out_of_stock || 'Out of stock'))));
        $container.append($legend);

        // Footer stats: total recorded changes + average of the prices shown.
        const avgPrice = prices.reduce((a, b) => a + b, 0) / prices.length;
        $('<div class="rg-stats"></div>')
            .text((i18n.changes || 'Number of changes') + ' ' + (series ? series.length : data.length) +
                  ', ' + (i18n.avg_price || 'average price') + ' ' + fmtPrice(avgPrice, currency))
            .appendTo($container);

        // Status pill (LOW / TYPICAL / HIGH) above the graph, like Google Flights. The sub-text
        // is phrased per status so it never reads awkwardly (e.g. "cheaper than 0%" when high).
        if (showOverlays) {
            const $pill = $('<div class="rg-status rg-status-' + summary.status + '"></div>');
            $pill.append($('<span class="rg-status-label"></span>').text(i18n['price_' + summary.status] || ''));
            let sub;
            if (summary.status === 'low') {
                sub = (i18n.cheaper_than || '').replace('%s', summary.cheaper_than_pct);
            } else if (summary.status === 'high') {
                sub = (i18n.pricier_than || '').replace('%s', summary.pricier_than_pct);
            } else {
                sub = i18n.typical_note || '';
            }
            if (sub) $pill.append($('<span class="rg-status-sub"></span>').text(sub));
            $container.prepend($pill);
        }
    }

    function buildTable($table, series, currency, i18n) {
        const $tbody = $table.find('tbody');
        if (!$tbody.length) return;
        $tbody.empty();
        series.slice().reverse().forEach(p => {
            let stock = '-';
            if (p.in_stock === true) stock = $('<span class="restock-badge in-stock"></span>').text(i18n.in_stock);
            else if (p.in_stock === false) stock = $('<span class="restock-badge out-of-stock"></span>').text(i18n.out_of_stock);
            const price = (p.price !== null && p.price !== undefined) ? fmtPrice(p.price, currency) : '-';
            $('<tr></tr>')
                .append($('<td></td>').text(fmtDateTime(p.timestamp)))
                .append($('<td></td>').append(stock))
                .append($('<td></td>').text(price))
                .appendTo($tbody);
        });
    }

    // Redraw a graph only if its container width actually changed (skips redundant redraws and
    // prevents ResizeObserver feedback loops).
    function redraw($c) {
        const ctx = $c.data('rg');
        if (!ctx) return;
        const w = Math.round($c.width());
        if (w === ctx.lastWidth) return;
        ctx.lastWidth = w;
        draw($c, ctx.series, ctx.currency, ctx.i18n, ctx.summary, ctx.height);
    }

    // Watch the container's own size, not just the window: the content area also changes width
    // when the action sidebar expands on hover (no window 'resize' event fires for that).
    const hasRO = typeof ResizeObserver !== 'undefined';
    let ro = null;
    if (hasRO) {
        let roTimer;
        const pending = new Set();
        ro = new ResizeObserver(function (entries) {
            entries.forEach(e => pending.add(e.target));
            clearTimeout(roTimer);
            roTimer = setTimeout(function () {
                pending.forEach(t => redraw($(t)));
                pending.clear();
            }, 120);
        });
    } else {
        // Fallback for browsers without ResizeObserver: window resize only.
        let resizeTimer;
        $(window).on('resize.restockgraph', function () {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(function () {
                $('.js-restock-graph').each(function () { redraw($(this)); });
            }, 150);
        });
    }

    // Public reusable renderer. Stores its context on the element and observes the element so
    // it redraws on any size change; usable from anywhere (e.g. the watchlist inline roll-down).
    window.renderRestockGraph = function (container, series, currency, i18n, summary, height) {
        const $c = $(container);
        if (!$c.length) return;
        const merged = $.extend({}, DEFAULT_I18N, i18n || {});
        // Seed lastWidth to the current width so the immediate ResizeObserver callback (which
        // fires once on observe()) doesn't trigger a redundant redraw.
        $c.addClass('js-restock-graph').data('rg', {
            series: series || [], currency: currency || '', i18n: merged, summary: summary || null,
            height: height || HEIGHT, lastWidth: Math.round($c.width())
        });
        draw($c, series || [], currency || '', merged, summary || null, height || HEIGHT);
        if (ro) {
            try { ro.unobserve($c[0]); } catch (e) {}
            ro.observe($c[0]);
        }
    };

    // Diff page bootstrap: fetch the timeline, render the graph + the data table.
    $(function () {
        const $container = $('#restock-graph');
        if (!$container.length || !window.restock_data_url) return;
        const i18n = $.extend({}, DEFAULT_I18N, window.restock_i18n || {});
        $.getJSON(window.restock_data_url).done(function (data) {
            const series = (data && data.series) || [];
            window.renderRestockGraph($container, series, (data && data.currency) || '', i18n, (data && data.summary) || null);
            buildTable($('#restock-history-table'), series, (data && data.currency) || '', i18n);
        }).fail(function () {
            $container.html($('<p class="pure-form-message-inline"></p>').text(i18n.load_error));
        });
    });

})(jQuery);
