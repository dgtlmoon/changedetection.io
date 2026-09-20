/**
 * AI change summary: start with POST, then wait for the result.
 *
 * Generation is an LLM round-trip, so the server does not hold the request open for it - the POST
 * returns 202 "pending" and the summary lands in the watch's cache some seconds later. There are
 * two ways to find out it arrived, and which one is in use is logged to the console:
 *
 *   realtime  Socket.IO is connected, so we sit idle until the server emits `llm_summary_ready`
 *             for this watch and then make exactly one request. No polling.
 *   polling   Socket.IO is off (settings > UI, batch mode) or not connected, so we re-check the
 *             route on an interval.
 *
 * Realtime carries identifiers only, never the summary text - the event just means "go look", and
 * the actual read still goes through the authenticated route. A watchdog re-checks once in a long
 * while even in realtime mode, so a dropped event cannot leave a permanent spinner.
 *
 * Why the start is a POST: it spends tokens and marks the watch as viewed, so it must not be
 * reachable from a cross-site GET. csrf.js ($.ajaxSetup) attaches X-CSRFToken to every non-GET
 * jQuery request, so nothing here has to handle the token. Parameters go in the query string for
 * both verbs (not the POST body) so the server reads them from request.args either way.
 *
 * When to stop waiting is the server's call, not ours. A local Ollama/vLLM box can spend many
 * minutes on prompt prefill and the server grants it up to LLM_LOCAL_TIMEOUT (30 min by default),
 * where a cloud provider gets LLM_TIMEOUT (5 min); on top of that the job may have been started
 * by another tab minutes ago, so even the right duration measured from our own first request is
 * the wrong answer. Every 'pending' reply therefore carries the deadline (`expires_in`, plus
 * `timeout_at` as the absolute instant) and we adopt it. Giving up earlier than the server does
 * means reporting a failure for a job that is still running and will still write its summary -
 * which is exactly what a fixed 180s limit used to do against a local model.
 */
window.llmSummary = (function () {
    var POLL_MS       = 1500;    // polling mode: first re-check
    var POLL_MAX_MS   = 15000;   // ...backing off to this, so a slow local model is not hammered
    var POLL_BACKOFF  = 1.5;
    var WATCHDOG_MS   = 45000;   // realtime mode: re-check once if no event turns up
    var MAX_WAIT_MS   = 180000;  // fallback only - replaced by the deadline the server sends
    var MAX_RESTARTS  = 1;       // an 'idle' reply means the job vanished (server restart); retry once
    var LOG           = '[llm-summary]';

    function withQuery(url, params) {
        var qs = params ? $.param(params) : '';
        if (!qs) return url;
        return url + (url.indexOf('?') >= 0 ? '&' : '?') + qs;
    }

    function errorFromXhr(xhr) {
        var body = xhr.responseJSON;
        if (body && body.error) return body.error;
        return 'AI summary request failed (HTTP ' + xhr.status + ').';
    }

    function realtimeSocket() {
        // realtime.js exposes the connection as window.cdioSocket when socket_io_enabled.
        var socket = window.cdioSocket;
        return (socket && socket.connected) ? socket : null;
    }

    /**
     * @param {object} opts
     *   url          {string}   the /llm-summary route for one watch
     *   uuid         {string}   watch uuid, used to match realtime events (optional - without it
     *                           this falls back to polling)
     *   params       {object}   query parameters (version pair, diff prefs) or null
     *   maxWaitMs    {number}   how long to wait before the server has told us otherwise
     *                           (optional); each 'pending' reply can push the deadline out
     *   onDone       {function} (summary, data)
     *   onError      {function} (message)
     *   isCancelled  {function} () => bool, stops all work when it returns true
     */
    function fetchSummary(opts) {
        var target      = withQuery(opts.url, opts.params);
        var restarts    = 0;
        var isCancelled = opts.isCancelled || function () { return false; };
        var socket      = opts.uuid ? realtimeSocket() : null;
        var watchdog    = null;
        var finished    = false;
        var onReady     = null;
        var deadline    = Date.now() + (opts.maxWaitMs || MAX_WAIT_MS);
        var pollDelay   = POLL_MS;

        console.log(LOG, socket
            ? 'realtime available - waiting for llm_summary_ready event (no polling)'
            : 'realtime unavailable - polling from ' + POLL_MS + 'ms, backing off to '
              + POLL_MAX_MS + 'ms');

        function cleanup() {
            finished = true;
            if (watchdog) { clearTimeout(watchdog); watchdog = null; }
            if (socket && onReady) { socket.off('llm_summary_ready', onReady); onReady = null; }
        }

        function done(data) {
            cleanup();
            opts.onDone(data.summary, data);
        }

        function fail(message) {
            cleanup();
            opts.onError(message);
        }

        function expired() {
            return Date.now() > deadline;
        }

        function adoptServerDeadline(data) {
            // Counted off `expires_in` rather than `timeout_at`, because that arrives as an
            // absolute server-side epoch and a browser clock minutes out of step with the server
            // would expire the wait the moment it was set. Only ever moves the deadline out: a
            // queued job reports a deadline that keeps sliding as it waits its turn, and a
            // shorter answer from a later poll must not cut short a wait already in progress.
            if (!data || typeof data.expires_in !== 'number') return;
            var wanted = Date.now() + (data.expires_in * 1000);
            if (wanted > deadline) {
                deadline = wanted;
                console.log(LOG, 'server will keep working for another ' + data.expires_in
                                 + 's - waiting with it');
            }
        }

        function stillPending() {
            // Nothing to do but wait: in realtime mode the event will tell us, in polling mode
            // the timer will.
            if (expired()) {
                // The last thing the server told us was 'pending', so the job has *not* failed -
                // it is still generating and will write to the cache when it lands. Say that,
                // instead of reporting a timeout the summary never had.
                fail('The AI summary is still being generated and is taking longer than usual - '
                     + 'reload this page shortly to see it.');
                return;
            }
            if (socket) {
                armWatchdog();
            } else {
                setTimeout(check, pollDelay);
                // Back off: a local model can run for minutes, and a 1.5s poll for all of it is
                // hundreds of pointless requests.
                pollDelay = Math.min(Math.round(pollDelay * POLL_BACKOFF), POLL_MAX_MS);
            }
        }

        function armWatchdog() {
            if (watchdog) clearTimeout(watchdog);
            watchdog = setTimeout(function () {
                if (finished || isCancelled()) return;
                if (!realtimeSocket()) {
                    console.log(LOG, 'socket dropped while waiting - switching to polling');
                    socket = null;
                    check();
                    return;
                }
                console.log(LOG, 'no llm_summary_ready event after ' + WATCHDOG_MS + 'ms - re-checking once');
                check();
            }, WATCHDOG_MS);
        }

        function handle(data, fromStart) {
            if (finished || isCancelled()) return;

            if (data.summary) { done(data); return; }
            if (data.error)   { fail(data.error); return; }

            adoptServerDeadline(data);

            if (data.status === 'idle') {
                // No cached summary and no job running: the process restarted mid-generation.
                if (fromStart || restarts >= MAX_RESTARTS) {
                    fail('AI summary could not be started.');
                    return;
                }
                restarts++;
                pollDelay = POLL_MS;
                console.log(LOG, 'job had vanished - restarting generation');
                start();
                return;
            }

            stillPending();
        }

        function check() {
            if (finished || isCancelled()) return;
            $.ajax({url: target, type: 'GET', dataType: 'json'})
                .done(function (data) { handle(data, false); })
                .fail(function (xhr) { if (!finished && !isCancelled()) fail(errorFromXhr(xhr)); });
        }

        function start() {
            $.ajax({url: target, type: 'POST', dataType: 'json'})
                .done(function (data) { handle(data, true); })
                .fail(function (xhr) { if (!finished && !isCancelled()) fail(errorFromXhr(xhr)); });
        }

        if (socket) {
            // Matched on uuid alone: the event cannot know which version pair this particular
            // view asked for, so a match only means "worth a look". The request that follows is
            // authoritative - if it comes back pending, the event was for a different pair and we
            // keep waiting.
            onReady = function (data) {
                if (finished || isCancelled() || !data || data.uuid !== opts.uuid) return;
                console.log(LOG, 'llm_summary_ready for', data.uuid, '- fetching summary');
                check();
            };
            socket.on('llm_summary_ready', onReady);
        }

        start();
    }

    return {fetch: fetchSummary};
})();
