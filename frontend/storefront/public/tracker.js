/*
 * Friction tracker - lightweight, dependency-free.
 * Sends structured events (CLAUDE.md §7.2) to POST /api/events.
 * Privacy: never reads input values (cards, passwords, OTPs, addresses); only event names + safe metadata.
 * Interaction signals (rage clicks) are computed in the browser and sent as summaries.
 */
(function () {
  var ENDPOINT = "/api/events";
  var RAGE_CLICKS = 4, RAGE_WINDOW_MS = 2000;

  function rid(prefix) { return prefix + Date.now().toString(36) + Math.random().toString(36).slice(2, 7); }
  function load(store, key, prefix) {
    try { var v = store.getItem(key); if (!v) { v = rid(prefix); store.setItem(key, v); } return v; }
    catch (e) { return rid(prefix); }
  }

  var sessionId = load(sessionStorage, "ft_sid", "live_");
  var userId = load(localStorage, "ft_uid", "anon-");
  var page = "home";
  var queue = [];
  var timer = null;
  var listeners = [];
  var URGENT = { payment_failed: 1, coupon_failed: 1, otp_failed: 1, otp_resend: 1, js_error: 1, exit: 1,
                 total_shown: 1, delivery_info_view: 1, size_unavailable_click: 1, rage_click: 1, order_placed: 1 };

  function flush() {
    if (timer) { clearTimeout(timer); timer = null; }
    if (!queue.length) return Promise.resolve(null);
    var batch = queue; queue = [];
    return fetch(ENDPOINT, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(batch) })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (res) {
        if (res) listeners.forEach(function (cb) { try { cb(res); } catch (e) {} });
        return res;
      })
      .catch(function () { return null; });
  }

  function track(event, pageName, metadata, ids) {
    if (pageName) page = pageName;
    ids = ids || {};
    queue.push({
      session_id: sessionId, user_id: userId, timestamp: new Date().toISOString(), event: event, page: page,
      product_id: ids.product_id || null, order_id: ids.order_id || null, metadata: metadata || {}
    });
    if (URGENT[event]) return flush();
    if (!timer) timer = setTimeout(flush, 600);
    return Promise.resolve(null);
  }

  // Rage-click detection: >= 4 clicks on the same element within 2 s -> one summary event.
  var clicks = [];
  document.addEventListener("click", function (e) {
    var el = e.target && e.target.closest ? e.target.closest("[data-track]") : null;
    if (!el) return;
    var name = el.getAttribute("data-track"), now = Date.now();
    clicks = clicks.filter(function (c) { return now - c.t < RAGE_WINDOW_MS; });
    clicks.push({ t: now, name: name });
    var same = clicks.filter(function (c) { return c.name === name; });
    if (same.length === RAGE_CLICKS) {
      track("rage_click", page, { element: name, clicks: same.length, window_ms: now - same[0].t });
    }
    if (el.hasAttribute("data-dead")) track("dead_click", page, { element: name });
  }, true);

  window.addEventListener("pagehide", function () {
    var exitEvent = [{ session_id: sessionId, user_id: userId, timestamp: new Date().toISOString(), event: "exit",
      page: page, product_id: null, order_id: null, metadata: {} }];
    try { navigator.sendBeacon(ENDPOINT, new Blob([JSON.stringify(queue.concat(exitEvent))], { type: "application/json" })); } catch (e) {}
  });

  window.FrictionTracker = {
    track: track,
    flush: flush,
    onResponse: function (cb) { listeners.push(cb); return function () { listeners = listeners.filter(function (x) { return x !== cb; }); }; },
    sessionId: function () { return sessionId; },
    newSession: function () {
      flush();
      sessionId = rid("live_");
      try { sessionStorage.setItem("ft_sid", sessionId); } catch (e) {}
      return sessionId;
    }
  };
})();
