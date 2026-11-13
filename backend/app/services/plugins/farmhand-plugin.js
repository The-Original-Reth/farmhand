// farmhand-plugin.js: for a plugin's page shown inside Farmhand. Load it with
//   <script src="/plugins/farmhand-plugin.js"></script>
// and the page gets Farmhand's colours as CSS variables on <html> (--farmhand-bg, --farmhand-panel,
// --farmhand-text-primary, --farmhand-amber... one per colour of GET /plugin-api/v1/farm, in kebab-case),
// `data-farmhand-mode` ("dark" or "light") and `color-scheme` set to match, and hears when the operator changes them.
//
//   window.farmhand.inFarmhand      true when the page is shown inside Farmhand
//   window.farmhand.theme           { mode, colors: { bg, panel, textPrimary, amber, ... }, font } once known, or null
//   window.farmhand.onTheme(fn)     fn(theme) now (when known) and on every change; returns a function that stops it
//   document "farmhand:theme"       the same, as an event (event.detail is the theme)
//   window.farmhand.onSave(fn)      a settings page with a Save of its own: Farmhand shows a Save button on the plugin's
//                                   heading row and calls fn() when it's pressed; fn returns (or resolves to) { ok, text },
//                                   shown beside the button. Returns a function that takes it away again
//   window.farmhand.changed(yes)    tells Farmhand whether there's anything to save (it lights its Save button up)
//
// Farmhand's page sends the theme with postMessage once this says it's ready, and again on every change.
// A page shown as a plugin's settings on Farmhand's Settings page (the manifest's settings_page) is drawn as tall as it
// is: this tells Farmhand its height whenever it changes ("farmhand:height"), so it never needs a scroll bar of its own.
(function () {
  if (window.farmhand) return;
  var listeners = [];
  var saver = null; // a settings page's save (onSave)
  var kebab = function (name) { return name.replace(/[A-Z]/g, function (ch) { return "-" + ch.toLowerCase(); }); };
  var api = {
    inFarmhand: window.parent !== window,
    theme: null,
    onSave: function (fn) {
      saver = fn;
      if (api.inFarmhand) window.parent.postMessage({ type: "farmhand:saves", saves: true }, "*");
      return function () {
        if (saver !== fn) return;
        saver = null;
        if (api.inFarmhand) window.parent.postMessage({ type: "farmhand:saves", saves: false }, "*");
      };
    },
    changed: function (yes) {
      if (api.inFarmhand) window.parent.postMessage({ type: "farmhand:changed", changed: !!yes }, "*");
    },
    onTheme: function (fn) {
      listeners.push(fn);
      if (api.theme) fn(api.theme);
      return function () { listeners = listeners.filter(function (f) { return f !== fn; }); };
    },
  };
  function apply(theme) {
    if (!theme || typeof theme !== "object" || !theme.colors) return;
    api.theme = theme;
    var root = document.documentElement;
    Object.keys(theme.colors).forEach(function (k) { root.style.setProperty("--farmhand-" + kebab(k), theme.colors[k]); });
    if (theme.font) root.style.setProperty("--farmhand-font", theme.font);
    root.setAttribute("data-farmhand-mode", theme.mode === "light" ? "light" : "dark");
    root.style.colorScheme = theme.mode === "light" ? "light" : "dark";
    listeners.slice().forEach(function (fn) { try { fn(theme); } catch (e) { console.error(e); } });
    document.dispatchEvent(new CustomEvent("farmhand:theme", { detail: theme }));
  }
  window.addEventListener("message", function (e) {
    if (e.source !== window.parent || !e.data) return;
    if (e.data.type === "farmhand:theme") apply(e.data.theme);
    if (e.data.type === "farmhand:save") {
      var id = e.data.id;
      var answer = function (r) {
        r = r && typeof r === "object" ? r : { ok: true, text: null };
        window.parent.postMessage({ type: "farmhand:saved", id: id, ok: r.ok !== false, text: r.text || null }, "*");
      };
      if (!saver) return answer({ ok: false, text: "This page has nothing to save." });
      Promise.resolve().then(saver).then(answer, function (err) { answer({ ok: false, text: String((err && err.message) || err) }); });
    }
  });
  window.farmhand = api;
  if (!api.inFarmhand) return;
  window.parent.postMessage({ type: "farmhand:ready" }, "*");
  var told = 0;
  function tellHeight() {
    var h = Math.ceil(document.body ? document.body.scrollHeight : document.documentElement.scrollHeight); // (the page's, not the frame's)
    if (h !== told) { told = h; window.parent.postMessage({ type: "farmhand:height", height: h }, "*"); }
  }
  function watch() {
    tellHeight();
    if (window.ResizeObserver) new ResizeObserver(tellHeight).observe(document.body || document.documentElement);
    else setInterval(tellHeight, 500);
  }
  if (document.body) watch(); else document.addEventListener("DOMContentLoaded", watch);
})();
