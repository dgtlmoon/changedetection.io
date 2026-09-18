/*
 * Queue activity sparkline — a compact "is it alive?" activity strip for the sidebar.
 *
 * UX goal: answer the user's gut question "is this thing actually doing anything?".
 *   - A pinned, gently PULSING leading dot at the right edge beats like a heartbeat
 *     even when totally idle, so the UI always reads as alive/monitoring — a frozen
 *     dot would read as broken.
 *   - Real in-flight work bumps the line, which then scrolls left across the window,
 *     so you can see it really does check things over the last few minutes.
 *
 * Signal plotted = queue_size + checking_now  (total in-flight work). Either being
 * non-zero lifts the trace; plain queue size alone sits at 0 while workers drain it.
 *
 * Rendering: a scrolling strip chart. The right edge is "now", the left edge is
 * "now - WINDOW_SECONDS". New samples always enter from the right; old data scrolls
 * off the left and fades out as it goes (left-edge brightness ramp).
 *
 * Hardening (lessons from common sparkline libs, e.g. fnando/sparkline #14/#24):
 *   - Autoscaled 0..max with headroom + a MIN floor, so it always stays inside the
 *     canvas height and never divides by zero on a flat/all-zero queue.
 *   - devicePixelRatio aware (crisp on retina), re-measured on resize (the rail
 *     expands 64px->190px on hover).
 *   - Pauses the rAF loop when the tab is hidden.
 *
 * History survives a full page reload via localStorage: we persist the queue/checking
 * EVENT LOG (a small step-function, not pixels). On load we sample that log across the
 * visible window, so the strip immediately shows the last few minutes instead of a
 * blank screen.
 *
 * Fed by the same Socket.IO 'queue_size' / 'checking_now' events as realtime.js.
 */
(function () {
    "use strict";

    const STORE_KEY = "cdio-queue-spark-v1";
    const WINDOW_SECONDS = 180;      // how much recent history the strip shows (a few minutes)
    const RETAIN_MS = WINDOW_SECONDS * 1000 * 1.5; // keep a little more than one screenful
    const MAX_EVENTS = 600;          // hard cap on stored events (localStorage size guard)
    const MIN_SCALE = 1;             // autoscale floor: avoids /0 and stops a 0/1 queue filling the panel
    const PULSE_MS = 1500;           // leading-dot heartbeat period — liveness even when idle
    const RISE_LERP = 0.30;          // autoscale rises quickly so a new bump shows promptly
    const FALL_LERP = 0.04;          // ...and falls slowly so it doesn't jitter
    const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const FRAME_MS = reduceMotion ? 250 : 100; // 10fps (plenty here); slower under reduced-motion

    // --- Shared state across all canvases (desktop rail + mobile drawer share one history) ---
    let eventLog = [];          // [{t: epoch_ms, v: number}] step-function of total activity
    let currentQueue = 0;
    let currentChecking = 0;

    function totalNow() { return currentQueue + currentChecking; }

    function stepValueAt(t) {
        // Last event at or before t (step function). Log is small; scan from the end.
        for (let i = eventLog.length - 1; i >= 0; i--) {
            if (eventLog[i].t <= t) return eventLog[i].v;
        }
        return NaN; // before our earliest knowledge -> leave that column blank
    }

    function pushEvent(now) {
        const v = totalNow();
        const last = eventLog[eventLog.length - 1];
        if (!last || last.v !== v) eventLog.push({ t: now, v: v });
    }

    function trimLog(now) {
        const cutoff = now - RETAIN_MS;
        // Keep the most recent event that predates the cutoff as a baseline anchor.
        let anchor = -1;
        for (let i = 0; i < eventLog.length; i++) {
            if (eventLog[i].t <= cutoff) anchor = i; else break;
        }
        if (anchor > 0) eventLog.splice(0, anchor);
        if (eventLog.length > MAX_EVENTS) eventLog.splice(0, eventLog.length - MAX_EVENTS);
    }

    function loadLog() {
        try {
            const raw = localStorage.getItem(STORE_KEY);
            if (!raw) return [];
            const parsed = JSON.parse(raw);
            const log = Array.isArray(parsed) ? parsed : parsed.log;
            if (!Array.isArray(log)) return [];
            eventLog = log.filter(e => e && typeof e.t === "number" && typeof e.v === "number");
            trimLog(Date.now());
            return eventLog;
        } catch (e) {
            return [];
        }
    }

    let saveTimer = null;
    function saveLog() {
        if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
        try {
            trimLog(Date.now());
            localStorage.setItem(STORE_KEY, JSON.stringify({ savedAt: Date.now(), log: eventLog }));
        } catch (e) { /* quota / private mode — history is best-effort */ }
    }
    function scheduleSave() {
        if (saveTimer) return;
        saveTimer = setTimeout(function () { saveTimer = null; saveLog(); }, 750);
    }

    // --- One Spark per canvas (different widths: rail vs drawer) ---
    function Spark(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext("2d");
        this.W = 1;
        this.cssW = 0;
        this.cssH = 0;
        this.rawW = -1;       // last-seen clientWidth/Height (incl. padding) — cheap change check
        this.rawH = -1;
        this.displayMax = MIN_SCALE;
        this.resize();
    }

    // Measure the canvas CONTENT box straight from the browser's computed CSS, so
    // sizing fully follows the stylesheet (padding/box styling from e.g. the
    // .action-sidebar-item class included) instead of hand-computed pixel maths.
    // clientWidth/Height already exclude border + scrollbar; subtract padding to
    // land on the exact content box that the canvas bitmap is drawn into.
    Spark.prototype.resize = function () {
        const rawW = this.canvas.clientWidth;
        const rawH = this.canvas.clientHeight;
        const cs = getComputedStyle(this.canvas);
        const padX = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0);
        const padY = (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
        const cssW = Math.max(0, Math.round(rawW - padX));
        const cssH = Math.max(0, Math.round(rawH - padY));
        this.rawW = rawW;
        this.rawH = rawH;
        if (cssW === this.cssW && cssH === this.cssH) return;
        this.cssW = cssW;
        this.cssH = cssH;
        const dpr = window.devicePixelRatio || 1;
        this.canvas.width = Math.max(1, Math.round(cssW * dpr));
        this.canvas.height = Math.max(1, Math.round(cssH * dpr));
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        this.W = Math.max(1, cssW);
    };

    // Wall-clock time represented by pixel column x: right edge = now, left edge = now - window.
    Spark.prototype.columnTime = function (x, now) {
        return now - ((this.W - 1 - x) / Math.max(1, this.W - 1)) * (WINDOW_SECONDS * 1000);
    };

    Spark.prototype.y = function (v) {
        const pad = 2;
        const h = Math.max(1, this.cssH - pad * 2);
        const t = Math.min(1, v / this.displayMax);
        return pad + h * (1 - t);
    };

    Spark.prototype.render = function (now) {
        if (this.cssW < 4 || this.cssH < 4) return;
        if (this.canvas.clientWidth !== this.rawW || this.canvas.clientHeight !== this.rawH) this.resize();

        const W = this.W;

        // Sample the step-function across the visible window (newest at right) and
        // find the autoscale max in the same pass.
        const ys = new Array(W);
        let maxV = MIN_SCALE;
        for (let x = 0; x < W; x++) {
            const v = stepValueAt(this.columnTime(x, now));
            ys[x] = v;
            if (!isNaN(v) && v > maxV) maxV = v;
        }
        const tv = totalNow();
        if (tv > maxV) maxV = tv;
        const rate = maxV > this.displayMax ? RISE_LERP : FALL_LERP;
        this.displayMax += (maxV - this.displayMax) * rate;

        const ctx = this.ctx;
        ctx.clearRect(0, 0, this.cssW, this.cssH);

        // Whole trace in a SINGLE stroke; the left->right fade (old data dimming as it
        // scrolls out of view) is a gradient strokeStyle rather than one stroke per
        // pixel column — ~140 draw calls collapse to 1.
        const grad = ctx.createLinearGradient(0, 0, this.cssW, 0);
        grad.addColorStop(0, "rgba(255,255,255,0.10)");
        grad.addColorStop(1, "rgba(255,255,255,0.95)");
        ctx.strokeStyle = grad;
        ctx.lineWidth = 1.5;
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.beginPath();
        let pen = false;
        for (let x = 0; x < W; x++) {
            const v = ys[x];
            if (isNaN(v)) { pen = false; continue; } // gap (no history yet) breaks the line
            const py = this.y(v);
            if (pen) ctx.lineTo(x + 0.5, py);
            else { ctx.moveTo(x + 0.5, py); pen = true; }
        }
        ctx.stroke();

        // Pinned, gently pulsing leading dot at the right edge = the "it's alive" tell.
        const rightV = isNaN(ys[W - 1]) ? tv : ys[W - 1];
        const pulse = 0.5 + 0.5 * Math.sin(((now % PULSE_MS) / PULSE_MS) * Math.PI * 2);
        ctx.save();
        ctx.shadowColor = "rgba(255,255,255,0.9)";
        ctx.shadowBlur = 4 + 5 * pulse;
        ctx.fillStyle = "rgba(255,255,255," + (0.75 + 0.25 * pulse).toFixed(3) + ")";
        ctx.beginPath();
        ctx.arc(W - 1.5, this.y(rightV), 1.6 + 0.7 * pulse, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
    };

    // --- Animation loop ---
    let instances = [];
    let rafId = null;
    let lastFrame = 0;

    function frame(ts) {
        rafId = requestAnimationFrame(frame);
        if (ts - lastFrame < FRAME_MS) return;
        lastFrame = ts;
        const now = Date.now();
        for (let i = 0; i < instances.length; i++) instances[i].render(now);
    }
    function start() { if (rafId === null) { lastFrame = 0; rafId = requestAnimationFrame(frame); } }
    function stop() { if (rafId !== null) { cancelAnimationFrame(rafId); rafId = null; } }

    function attach(socket) {
        if (!socket) return;
        socket.on("queue_size", function (d) {
            currentQueue = parseInt(d && d.q_length, 10) || 0;
            pushEvent(Date.now());
            scheduleSave();
        });
        socket.on("checking_now", function (d) {
            currentChecking = parseInt(d && d.count, 10) || 0;
            pushEvent(Date.now());
            scheduleSave();
        });
    }

    function init() {
        const canvases = Array.prototype.slice.call(document.querySelectorAll("canvas.queue-spark"));
        if (!canvases.length) return;

        loadLog();

        // Seed current levels from the server-rendered numbers so the line starts at
        // the right height before the first socket event arrives.
        const qEl = document.querySelector(".queue-size-int");
        const cEl = document.querySelector(".checking-now-int");
        if (qEl) currentQueue = parseInt(qEl.textContent, 10) || 0;
        if (cEl) currentChecking = parseInt(cEl.textContent, 10) || 0;
        pushEvent(Date.now());

        instances = canvases.map(function (c) { return new Spark(c); });

        if (typeof ResizeObserver !== "undefined") {
            const ro = new ResizeObserver(function () {
                for (let i = 0; i < instances.length; i++) instances[i].resize();
            });
            canvases.forEach(function (c) { ro.observe(c); });
        }

        document.addEventListener("visibilitychange", function () {
            if (document.hidden) { saveLog(); stop(); }
            else { start(); }
        });
        window.addEventListener("beforeunload", saveLog);

        // realtime.js exposes the socket either already on window or via this event.
        if (window.cdioSocket) attach(window.cdioSocket);
        else document.addEventListener("cdio:socket-ready", function (e) { attach(e.detail && e.detail.socket); });

        start();
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();
})();
