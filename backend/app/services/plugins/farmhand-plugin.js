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
//
// Farmhand's page sends the theme with postMessage once this says it's ready, and again on every change.
(function () {
  if (window.farmhand) return;
  var listeners = [];
  var kebab = function (name) { return name.replace(/[A-Z]/g, function (ch) { return "-" + ch.toLowerCase(); }); };
  var api = {
    inFarmhand: window.parent !== window,
    theme: null,
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
    if (e.source !== window.parent || !e.data || e.data.type !== "farmhand:theme") return;
    apply(e.data.theme);
  });
  window.farmhand = api;
  if (api.inFarmhand) window.parent.postMessage({ type: "farmhand:ready" }, "*");
})();
