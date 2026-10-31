import React, { useEffect, useRef, useState } from "react";
import { Archive, Cctv, Layers, Palette, Printer, Settings, Zap } from "lucide-react";
import { c, fs, ui } from "./theme.js";
import { monoText, uiText } from "./styles.js";
import { applyAppearance, loadAppearance, normalizeAppearance, saveAppearance } from "./appearance.js";
import { AppearanceSection } from "./AppearanceSection.jsx";
import { API_BASE, errorText, getConfig, saveConfig, saveConfigOnExit } from "./api.js";
import { DataProvider, useData } from "./data.jsx";
import { readStored, writeStored } from "./lib/storage.js";

import { CompareTray } from "./compare/CompareTray.jsx";
import { DiffView } from "./compare/DiffView.jsx";
import { Modal } from "./components/common/dialogs.jsx";
import { ModelsSection } from "./models/ModelsSection.jsx";
import { loadModelSort, normalizeModelSort, saveModelSort } from "./models/modelSort.js";
import { PrintersSection } from "./printers/PrintersSection.jsx";
import { PowerSection } from "./power/PowerSection.jsx";
import { MonitorSection } from "./monitor/MonitorSection.jsx";
import { StorageSection } from "./storage/StorageSection.jsx";

function Crumb({ items, onJump }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
      {items.map((it, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {i > 0 && <span style={{ color: c.textFaint }}>/</span>}
          <button
            onClick={() => onJump(i)}
            disabled={i === items.length - 1}
            style={{
              ...ui,
              background: "none",
              border: "none",
              padding: 0,
              fontSize: fs(14),
              cursor: i === items.length - 1 ? "default" : "pointer",
              color: i === items.length - 1 ? c.heading : c.textMuted,
              fontWeight: i === items.length - 1 ? 600 : 400,
            }}
          >
            {it}
          </button>
        </div>
      ))}
    </div>
  );
}

const PENDING_CONFIG_KEY = "farmhand.configPending"; // changes not yet confirmed by the server

// The menu's sections, in menu order, each at its own address (/models, /printers…); the bare address is Models
const SECTIONS = [
  { key: "models", label: "Models", Icon: Layers },
  { key: "printers", label: "Printers", Icon: Printer },
  { key: "power", label: "Power", Icon: Zap },
  { key: "monitor", label: "Monitor", Icon: Cctv },
  { key: "settings", label: "Settings", Icon: Settings }, // where files are stored, network shares, the settings copy
  { key: "appearance", label: "Appearance", Icon: Palette },
];
const sectionInAddress = () => {
  let key = window.location.pathname.replace(/^\/+|\/+$/g, "");
  if (key === "storage") key = "settings"; // its old address, so bookmarks still open it
  return SECTIONS.some((s) => s.key === key) ? key : "models";
};

// A whole page saying something went wrong (the API can't be reached, or drawing a page failed), with one button
function FullPageMessage({ children, action, onAction }) {
  return (
    <div style={{ ...ui, display: "flex", flexDirection: "column", gap: 12, alignItems: "center", justifyContent: "center", height: "100vh", background: c.bg, color: c.amber, padding: 24, textAlign: "center" }}>
      {children}
      <button
        onClick={onAction}
        style={{ ...ui, fontSize: fs(13), background: c.amberDim, color: c.amber, border: `1px solid ${c.amber}`, borderRadius: 4, padding: "7px 14px", cursor: "pointer" }}
      >
        {action}
      </button>
    </div>
  );
}

// Two config patches as one, the later winning. Each preference is saved on its own on the server, so two changed
// close together are both kept.
const mergePatches = (a, b) => {
  const merged = { ...a, ...b };
  if (a.preferences && b.preferences) merged.preferences = { ...a.preferences, ...b.preferences };
  return merged;
};

// Appearance has its own page (the last menu item). It only needs to know whether a settings folder is
// chosen, to say where a change was kept.
function AppearancePage({ appearance, saved, onChange, onSave, onDiscard, saveState }) {
  const [locationPath, setLocationPath] = useState(null);
  const refresh = () =>
    getConfig()
      .then((r) => setLocationPath(r.location.isSet ? r.location.path : null))
      .catch(() => {});
  useEffect(() => {
    refresh();
  }, []);
  useEffect(() => {
    if (saveState?.phase === "saved") refresh();
  }, [saveState]);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 820 }}>
      <AppearanceSection
        appearance={appearance}
        saved={saved}
        onChange={onChange}
        onSave={onSave}
        onDiscard={onDiscard}
        saveState={saveState}
        locationPath={locationPath}
      />
    </div>
  );
}

// `npm run mock`: the real UI on built-in sample data (frontend/mock/). Said plainly in the sidebar, so the mockup
// is never mistaken for the real farm, with a way back to the untouched sample data.
const MOCKUP = !!import.meta.env.VITE_MOCK;
function MockupBadge() {
  const [busy, setBusy] = useState(false);
  return (
    <div data-testid="mockup-badge" style={{ margin: "14px 4px 0", border: `1px dashed ${c.amber}`, borderRadius: 4, padding: "10px 12px", background: c.amberDim }}>
      <div style={{ ...ui, fontSize: fs(12), fontWeight: 600, color: c.amber, marginBottom: 4 }}>Mockup</div>
      <div style={uiText(11, c.textMuted, { lineHeight: 1.5, marginBottom: 8 })}>
        Sample data, no real farm. Changes last until the mockup restarts.
      </div>
      <button
        data-testid="mockup-reset"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          await fetch(`${API_BASE}/__reset`, { method: "POST" });
          window.location.reload();
        }}
        style={{ ...ui, fontSize: fs(11), background: "none", color: c.amber, border: `1px solid ${c.amber}`, borderRadius: 3, padding: "3px 8px", cursor: busy ? "default" : "pointer" }}
      >
        {busy ? "Resetting…" : "Reset sample data"}
      </button>
    </div>
  );
}

function FarmhandApp() {
  const { printers, sourceModels, bundles, bundleTitle, versionIndex, loading, error, refresh } = useData();
  const [section, setSection] = useState(sectionInAddress); // one of SECTIONS, as the address says (/printers…)
  const [printerPath, setPrinterPath] = useState([{ label: "Printers" }]);
  const [modelPath, setModelPath] = useState([{ label: "Models" }]);
  // a section opened from the menu (or by Back / Forward) starts at its top: the list, not a model or printer
  const openSection = (key) => {
    setSection(key);
    if (key === "printers") setPrinterPath([{ label: "Printers" }]);
    else if (key === "models") setModelPath([{ label: "Models" }]);
  };
  useEffect(() => {
    const back = () => {
      setPreview(null);
      openSection(sectionInAddress());
    };
    window.addEventListener("popstate", back);
    return () => window.removeEventListener("popstate", back);
  }, []);
  // Appearance: colour scheme, text brightness, font and size. Held HERE (not in a provider above) so that a
  // change re-renders everything below: components read the live theme (theme.js) as they render.
  // The server keeps these (so every browser and device shows the same look), and copies them to the network
  // folder chosen on the Storage page. What this browser remembers is only used to paint the right look at
  // once, before the server has answered.
  const [appearance, setAppearance] = useState(loadAppearance); // the SAVED look
  const [preview, setPreview] = useState(null); // a look being tried on the Appearance page, not saved yet (null = none)
  const [modelSort, setModelSort] = useState(loadModelSort);
  const [monitorOrder, setMonitorOrder] = useState([]); // the Monitor page's cameras as dragged into order (kept on the server)
  const [monitorMaxZoom, setMonitorMaxZoom] = useState(4); // how far in a Monitor camera can be zoomed
  const [saveState, setSaveState] = useState({ phase: "idle" }); // idle | saving | saved | error
  const pendingSave = useRef({});
  const saveTimer = useRef(null);
  applyAppearance(preview || appearance); // a preview shows live; it only becomes the saved look when Save is pressed

  // Changes the server hasn't confirmed yet are also written down in this browser. If the page is closed, or the
  // server is unreachable, they're sent on the next visit instead of being overwritten by the server's older copy.
  const rememberPending = (patch) => writeStored(PENDING_CONFIG_KEY, patch && Object.keys(patch).length ? patch : null);

  const adoptServerConfig = (config) => {
    const a = normalizeAppearance(config.appearance);
    const sort = normalizeModelSort(config.preferences?.model_sort);
    setAppearance(a);
    saveAppearance(a);
    setModelSort(sort);
    saveModelSort(sort);
    setMonitorOrder(Array.isArray(config.preferences?.monitor_order) ? config.preferences.monitor_order : []);
    setMonitorMaxZoom(config.preferences?.monitor_max_zoom || 4);
  };
  const loadServerConfig = () =>
    getConfig()
      .then(({ config }) => adoptServerConfig(config))
      .catch(() => {
        /* the server isn't answering: carry on with what this browser remembers */
      });
  useEffect(() => {
    const pending = readStored(PENDING_CONFIG_KEY);
    if (pending && Object.keys(pending).length) {
      // changes made here that never reached the server: send them first, then show what the server now holds
      saveConfig(pending)
        .then((r) => {
          rememberPending(null);
          adoptServerConfig(r.config);
        })
        .catch(() => {
          /* still can't reach it: keep them for next time and carry on with what this browser remembers */
        });
    } else {
      loadServerConfig();
    }
    // closing or leaving the page within the short wait below must not lose the last change
    const onHide = () => {
      if (Object.keys(pendingSave.current).length) saveConfigOnExit(pendingSave.current);
    };
    window.addEventListener("pagehide", onHide);
    return () => window.removeEventListener("pagehide", onHide);
  }, []);

  const flushSave = async () => {
    const patch = pendingSave.current;
    pendingSave.current = {};
    try {
      const result = await saveConfig(patch);
      rememberPending(pendingSave.current); // anything changed while that was in flight is still waiting
      setSaveState({ phase: "saved", mirror: result.mirror });
    } catch (e) {
      pendingSave.current = mergePatches(patch, pendingSave.current); // not delivered: keep it, newer values winning
      rememberPending(pendingSave.current);
      setSaveState({ phase: "error", message: errorText(e) });
    }
  };
  // A slider drags through many values: wait for it to settle rather than rewriting the network file for each
  const queueSave = (patch, { immediate = false } = {}) => {
    pendingSave.current = mergePatches(pendingSave.current, patch);
    rememberPending(pendingSave.current);
    setSaveState({ phase: "saving" });
    clearTimeout(saveTimer.current);
    if (immediate) flushSave();
    else saveTimer.current = setTimeout(flushSave, 400);
  };

  // Appearance: changes are a live PREVIEW until Save is pressed. Leaving the page without saving undoes them.
  const sameLook = (a, b) =>
    a.scheme === b.scheme && a.contrast === b.contrast && a.font === b.font && a.size === b.size && a.file_name_color === b.file_name_color;
  const changeAppearance = (next) => setPreview(sameLook(next, appearance) ? null : next);
  const discardAppearance = () => setPreview(null);
  const commitAppearance = () => {
    if (!preview) return;
    const next = preview;
    setAppearance(next);
    saveAppearance(next);
    setPreview(null);
    queueSave({ appearance: next }, { immediate: true });
  };
  const changeModelSort = (next) => {
    setModelSort(next);
    saveModelSort(next);
    queueSave({ preferences: { model_sort: next } });
  };
  // The Monitor page's Save layout: sent at once, and only taken as saved once the server says so (an error is shown
  // there, by the button)
  const saveMonitorOrder = async (next) => {
    const r = await saveConfig({ preferences: { monitor_order: next } });
    setMonitorOrder(r.config.preferences.monitor_order);
  };
  const changeMonitorMaxZoom = (next) => {
    setMonitorMaxZoom(next);
    queueSave({ preferences: { monitor_max_zoom: next } });
  };
  const [compareSelection, setCompareSelection] = useState([]); // VERSION ids, in selection order
  const [diffModalOpen, setDiffModalOpen] = useState(false);

  // If what we're looking at gets deleted (a model folder, a printer), fall back
  // to the list instead of rendering a page for something that no longer exists.
  // (These hooks must stay above the early returns below.)
  const modelPathSafe = modelPath.every((seg) => seg.modelId == null || sourceModels.some((m) => m.id === seg.modelId))
    ? modelPath
    : [{ label: "Models" }];
  const printerPathSafe = printerPath.every(
    (seg) =>
      (seg.printerId == null || printers.some((p) => p.id === seg.printerId)) &&
      (seg.bundleId == null || bundles.some((b) => b.id === seg.bundleId))
  )
    ? printerPath
    : [{ label: "Printers" }];

  useEffect(() => {
    if (modelPathSafe !== modelPath) setModelPath(modelPathSafe);
  }, [modelPathSafe, modelPath]);
  useEffect(() => {
    if (printerPathSafe !== printerPath) setPrinterPath(printerPathSafe);
  }, [printerPathSafe, printerPath]);

  // Drop deleted versions from the compare selection
  useEffect(() => {
    setCompareSelection((prev) => {
      const next = prev.filter((id) => versionIndex[id]);
      if (next.length === prev.length) return prev;
      setDiffModalOpen(false);
      return next;
    });
  }, [versionIndex]);

  if (loading) {
    return (
      <div style={{ ...ui, display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", background: c.bg, color: c.textFaint }}>
        Loading Farmhand…
      </div>
    );
  }
  if (error) {
    return (
      <FullPageMessage action="Retry" onAction={refresh}>
        <div>Couldn't reach the API: {error}</div>
        <div style={{ color: c.textFaint, fontSize: fs(13) }}>Checked {API_BASE} — is the backend running?</div>
      </FullPageMessage>
    );
  }

  const toggleCompareSelect = (versionId) => {
    // A compare is between two versions: picking a third replaces the oldest pick instead of being ignored
    setCompareSelection((prev) =>
      prev.includes(versionId)
        ? prev.filter((id) => id !== versionId)
        : prev.length >= 2
          ? [prev[1], versionId]
          : [...prev, versionId]
    );
    setDiffModalOpen(false);
  };
  const removeFromCompare = (versionId) => {
    setCompareSelection((prev) => prev.filter((id) => id !== versionId));
    setDiffModalOpen(false);
  };
  const clearCompare = () => {
    setCompareSelection([]);
    setDiffModalOpen(false);
  };

  const path =
    section === "printers" ? printerPathSafe : section === "models" ? modelPathSafe : [{ label: SECTIONS.find((s) => s.key === section).label }];
  const setPath = section === "printers" ? setPrinterPath : section === "models" ? setModelPath : () => {};
  const diffLeft = versionIndex[compareSelection[0]];
  const diffRight = versionIndex[compareSelection[1]];

  const crumbLabels = path.map((seg, i) => {
    if (seg.label) return seg.label;
    if (section === "printers") {
      const printer = printers.find((p) => p.id === seg.printerId);
      if (seg.bundleId) {
        const bundle = bundles.find((b) => b.id === seg.bundleId);
        return bundleTitle(bundle);
      }
      return printer.name;
    } else {
      const model = sourceModels.find((m) => m.id === seg.modelId);
      return model.name;
    }
  });

  // Each section has an address of its own (/printers, /monitor…), so a menu item is a link: Ctrl-click, middle-click
  // or "Open in new tab" opens that section in another tab, and a plain click changes section here.
  const counts = { models: sourceModels.length, printers: printers.length };
  const navItem = ({ key, label, Icon }) => (
    <a
      key={key}
      href={`/${key}`}
      onClick={(e) => {
        if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return; // the browser opens a new tab
        e.preventDefault();
        if (key !== "appearance") setPreview(null); // an unsaved preview is undone when you leave the page
        openSection(key);
        if (window.location.pathname !== `/${key}`) window.history.pushState(null, "", `/${key}`);
      }}
      style={{
        boxSizing: "border-box",
        textDecoration: "none",
        display: "flex",
        alignItems: "center",
        gap: 10,
        width: "100%",
        padding: "9px 14px",
        borderRadius: 4,
        border: "none",
        background: section === key ? c.panelAlt : "transparent",
        color: section === key ? c.textPrimary : c.textMuted,
        cursor: "pointer",
        ...ui,
        fontSize: fs(14),
        textAlign: "left",
        marginBottom: 2,
      }}
    >
      <Icon size={16} color={section === key ? c.amber : c.textFaint} />
      <span style={{ flex: 1 }}>{label}</span>
      <span style={monoText(11, c.textFaint)}>{counts[key] ?? ""}</span>
    </a>
  );

  return (
    <div
      style={{
        ...ui,
        display: "flex",
        height: "100vh",
        background: c.bg,
        color: c.textPrimary,
      }}
    >
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
        * { box-sizing: border-box; }
      `}</style>

      {/* Sidebar */}
      <div
        style={{
          width: 220,
          borderRight: `1px solid ${c.border}`,
          background: c.panel,
          padding: 16,
          flexShrink: 0,
          display: "flex",
          flexDirection: "column",
          overflowY: "auto", // a window too short for all of it scrolls the menu, rather than covering anything
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 24, padding: "0 4px" }}>
          <Archive size={18} color={c.amber} />
          <span style={{ fontSize: fs(15), fontWeight: 600, letterSpacing: 0.2, color: c.heading }}>Farmhand</span>
        </div>
        {SECTIONS.map(navItem)}
        <div style={{ borderTop: `1px solid ${c.border}`, marginTop: 12, paddingTop: 12 }}>
          <div style={{ fontSize: fs(11), color: c.textFaint, padding: "0 14px", lineHeight: 1.6 }}>
            An archive: nothing here re-slices, and a print only goes to a printer when you send it.
          </div>
        </div>
        {MOCKUP && <MockupBadge />}
        {/* at the foot of the menu: the 3D Printing Elves logo (frontend/public), their donation page in a new tab when clicked */}
        <a
          href="https://www.3dprintingelves.org/donate-now"
          target="_blank"
          rel="noreferrer"
          data-testid="elves-logo"
          title="Donate to 3D Printing Elves (opens their donation page in a new tab)"
          style={{ display: "block", marginTop: "auto", padding: "16px 14px 0", textDecoration: "none", flexShrink: 0 }}
        >
          <img src="/3d-printing-elves.webp" alt="3D Printing Elves" width={150} height={110} style={{ display: "block", width: 150, height: "auto" }} />
          <span data-testid="elves-thanks" style={{ display: "block", width: 150, marginTop: 6, textAlign: "center", fontSize: fs(11), color: c.textMuted, lineHeight: 1.5 }}>
            Your support is appreciated
          </span>
        </a>
      </div>

      {/* Main */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <div
          style={{
            padding: "16px 24px",
            borderBottom: `1px solid ${c.border}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <Crumb items={crumbLabels} onJump={(i) => setPath(path.slice(0, i + 1))} />
        </div>
        <div style={{ padding: 24, paddingBottom: compareSelection.length > 0 ? 80 : 24, overflow: "auto", flex: 1 }}>
          {section === "printers" ? (
            <PrintersSection
              path={printerPathSafe}
              setPath={setPrinterPath}
              compareSelection={compareSelection}
              toggleCompareSelect={toggleCompareSelect}
            />
          ) : section === "models" ? (
            <ModelsSection
              path={modelPathSafe}
              setPath={setModelPath}
              compareSelection={compareSelection}
              toggleCompareSelect={toggleCompareSelect}
              sort={modelSort}
              onSortChange={changeModelSort}
            />
          ) : section === "power" ? (
            <PowerSection />
          ) : section === "monitor" ? (
            <MonitorSection
              order={monitorOrder} onSave={saveMonitorOrder} maxZoom={monitorMaxZoom} onMaxZoom={changeMonitorMaxZoom}
            />
          ) : section === "appearance" ? (
            <AppearancePage
              appearance={preview || appearance}
              saved={appearance}
              onChange={changeAppearance}
              onSave={commitAppearance}
              onDiscard={discardAppearance}
              saveState={saveState}
            />
          ) : (
            <StorageSection onSettingsRestored={loadServerConfig} />
          )}
        </div>
      </div>

      <CompareTray
        selection={compareSelection}
        onRemove={removeFromCompare}
        onClear={clearCompare}
        onCompare={() => setDiffModalOpen(true)}
      />

      {diffModalOpen && diffLeft && diffRight && (
        <Modal title="Compare 3MF files" onClose={() => setDiffModalOpen(false)} width={1500}>
          <DiffView
            left={diffLeft}
            right={diffRight}
            onClose={() => setDiffModalOpen(false)}
          />
        </Modal>
      )}
    </div>
  );
}

// Last line of defense: if any component throws while rendering, show what
// happened instead of leaving a blank page.
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <FullPageMessage action="Reload" onAction={() => window.location.reload()}>
        <div>Something went wrong displaying this page.</div>
        <div style={monoText(12, c.textFaint, { maxWidth: 640, wordBreak: "break-word" })}>
          {String(this.state.error?.message || this.state.error)}
        </div>
      </FullPageMessage>
    );
  }
}

export default function App() {
  return (
    <ErrorBoundary>
      <DataProvider>
        <FarmhandApp />
      </DataProvider>
    </ErrorBoundary>
  );
}
