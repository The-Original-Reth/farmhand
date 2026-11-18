import React from "react";
import { Menu } from "lucide-react";
import { usePhone } from "./hooks/useMediaQuery.js";
import { c, fixed, fs, ui } from "./theme.js";
import { monoText } from "./styles.js";
import { API_BASE, errorText } from "./api.js";
import { DataProvider, useData } from "./data.jsx";

import { CompareTray } from "./compare/CompareTray.jsx";
import { DiffView } from "./compare/DiffView.jsx";
import { Modal } from "./components/common/dialogs.jsx";
import { ModelsSection } from "./models/ModelsSection.jsx";
import { ProjectsSection } from "./projects/ProjectsSection.jsx";
import { PrintersSection } from "./printers/PrintersSection.jsx";
import { MaintenanceBanner } from "./printers/MaintenanceBanner.jsx";
import { PowerSection } from "./power/PowerSection.jsx";
import { FarmCostSection } from "./farmcost/FarmCostSection.jsx";
import { EnergyPricesContext } from "./lib/energyPrice.js";
import { MonitorSection } from "./monitor/MonitorSection.jsx";
import { StorageSection } from "./storage/StorageSection.jsx";
import { ToolsSection } from "./tools/ToolsSection.jsx";
import { PluginsSection } from "./plugins/PluginsSection.jsx";
import { PluginPage } from "./plugins/PluginPage.jsx";
import { usePlugins } from "./plugins/usePlugins.js";
import { StreamControlSection } from "./streamControl/StreamControlSection.jsx";

const STREAM_CONTROL = "stream-control"; // the plugin built into Farmhand: its page is Farmhand's own, not a plugin's iframe
import { AppearancePage, Crumb, FullPageMessage, LoadingPage } from "./shell/pages.jsx";
import { Sidebar } from "./shell/Sidebar.jsx";
import { useCompare } from "./shell/useCompare.js";
import { PLUGIN_SECTION, pluginSection, useNavigation } from "./shell/useNavigation.js";
import { useSavedSettings } from "./shell/useSavedSettings.js";

// The page of the section open now
function SectionPage({ section, nav, compare, settings, plugins }) {
  const { appearance, energy, farmCost, monitor, modelSort, printerSort, saveState, tools } = settings;
  const comparing = { compareSelection: compare.selection, toggleCompareSelect: compare.toggle };
  const pluginId = section.match(PLUGIN_SECTION)?.[1];
  if (pluginId === STREAM_CONTROL) {
    // built into Farmhand: its own page, while it's switched on
    const on = plugins.builtin.find((p) => p.id === STREAM_CONTROL)?.enabled;
    if (!on) {
      return (
        <div data-testid="stream-control-off" style={{ ...ui, fontSize: fs(13), color: c.textMuted }}>
          {plugins.loaded ? (
            <>
              Stream control is switched off.{" "}
              <button type="button" onClick={() => nav.goTo("plugins")} style={{ ...ui, fontSize: fs(13), background: "none", border: "none", padding: 0, color: c.amber, textDecoration: "underline", cursor: "pointer" }}>
                Switch it on on the Plugins page
              </button>{" "}
              to use it.
            </>
          ) : "Loading…"}
        </div>
      );
    }
    return <StreamControlSection onOpenPlugin={(id) => nav.goTo(pluginSection(id))} onOpenPlugins={() => nav.goTo("plugins")} />;
  }
  if (pluginId) {
    return (
      <PluginPage
        pluginId={pluginId}
        plugin={plugins.withPages.find((p) => p.id === pluginId)}
        loaded={plugins.loaded}
        onRetry={plugins.refresh}
        onOpenPlugins={() => nav.goTo("plugins")}
      />
    );
  }
  switch (section) {
    case "printers":
      return (
        <PrintersSection path={nav.printers.path} setPath={nav.printers.setPath} {...comparing} sort={printerSort.value} onSortChange={printerSort.change} />
      );
    case "models":
      return (
        <ModelsSection path={nav.models.path} setPath={nav.models.setPath} {...comparing} sort={modelSort.value} onSortChange={modelSort.change} />
      );
    case "projects":
      return (
        <ProjectsSection
          path={nav.projects.path}
          setPath={nav.projects.setPath}
          onOpenModel={(modelId) => nav.open("models", { modelId })}
          onOpenPrinter={(printerId) => nav.open("printers", { printerId })}
        />
      );
    case "farm-cost":
      return <FarmCostSection order={farmCost.order} onOrder={farmCost.changeOrder} />;
    case "power":
      return <PowerSection prices={energy.prices} onEnergyPrice={energy.changePrice} onMonthPrice={energy.changeMonthPrice} saveState={saveState} />;
    case "monitor":
      return <MonitorSection order={monitor.order} onSave={monitor.saveOrder} maxZoom={monitor.maxZoom} onMaxZoom={monitor.changeMaxZoom} />;
    case "tools":
      return <ToolsSection links={tools.links} onSave={tools.save} />;
    case "plugins":
      return <PluginsSection plugins={plugins.plugins} builtin={plugins.builtin} onChanged={plugins.refresh} onOpenPage={(id) => nav.goTo(pluginSection(id))} />;
    case "appearance":
      return (
        <AppearancePage
          appearance={appearance.shown}
          saved={appearance.saved}
          onChange={appearance.change}
          onSave={appearance.save}
          onDiscard={appearance.discard}
          saveState={saveState}
        />
      );
    default:
      return (
        <StorageSection
          onSettingsRestored={settings.loadServerConfig}
          plugins={plugins.plugins}
          onOpenPluginPage={(id) => nav.goTo(pluginSection(id))}
          onOpenPlugins={() => nav.goTo("plugins")}
        />
      );
  }
}

function FarmhandApp() {
  const { printers, sourceModels, bundles, projects, bundleTitle, versionIndex, loading, error, refresh, refreshPrinters } = useData();
  // Held HERE (not in a provider above) so that a change of look re-renders everything below
  const settings = useSavedSettings();
  const plugins = usePlugins(); // for the menu's plugin pages and the Plugins page
  // an unsaved look is undone when you leave the Appearance page
  const nav = useNavigation({
    printers,
    sourceModels,
    bundles,
    projects,
    bundleTitle,
    pluginName: (id) => [...plugins.builtin, ...plugins.plugins].find((p) => p.id === id)?.page?.menu || id,
    onLeave: (to) => to !== "appearance" && settings.appearance.discard(),
  });
  const compare = useCompare(versionIndex);
  // on a phone the menu is a drawer, opened from the button at the left of the top bar
  const phone = usePhone();
  const [menuOpen, setMenuOpen] = React.useState(false);
  const gap = phone ? 12 : 24; // the space around a page

  if (loading) return <LoadingPage />;
  if (error) {
    return (
      <FullPageMessage action="Retry" onAction={refresh}>
        <div>Couldn't reach the API: {error}</div>
        <div style={{ color: c.textFaint, fontSize: fs(13) }}>Checked {API_BASE} — is the backend running?</div>
      </FullPageMessage>
    );
  }

  return (
    <EnergyPricesContext.Provider value={settings.energy.prices}>
    <div
      style={{
        ...ui,
        display: "flex",
        height: phone ? "100dvh" : "100vh", // a phone's own address bar comes and goes; dvh is what's left beside it
        background: c.bg,
        color: c.textPrimary,
      }}
    >
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
        * { box-sizing: border-box; }
      `}</style>

      <Sidebar
        current={nav.section}
        counts={{ models: sourceModels.length, projects: projects.length, printers: printers.length }}
        plugins={plugins.withPages}
        onOpen={nav.goTo}
        phone={phone}
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
      />

      {/* Main */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <div
          style={{
            padding: phone ? "10px 12px" : "16px 24px",
            borderBottom: `1px solid ${c.border}`,
            display: "flex",
            alignItems: "center",
            justifyContent: phone ? "flex-start" : "space-between",
            flexWrap: phone ? "wrap" : undefined,
            gap: phone ? 10 : undefined,
            position: "relative",
          }}
        >
          {phone && (
            <button
              type="button" data-testid="menu-open" onClick={() => setMenuOpen(true)} aria-label="Open the menu" aria-expanded={menuOpen}
              style={{ background: "none", border: `1px solid ${c.border}`, borderRadius: 4, padding: 6, cursor: "pointer", display: "flex", flexShrink: 0 }}
            >
              <Menu size={20} color={c.textMuted} />
            </button>
          )}
          <Crumb items={nav.crumbs()} onJump={nav.jumpTo} />
          {/* the middle of the top bar (below the path on a phone): printers whose service is due, on every page, and on
              the Stream plugin's page the warning that the cameras see what the printers' panels reflect */}
          <div
            style={phone
              ? { width: "100%", display: "flex", flexDirection: "column", gap: 4 }
              : { position: "absolute", left: "50%", top: "50%", transform: "translate(-50%, -50%)", maxWidth: "50%",
                  display: "flex", flexDirection: "column", alignItems: "center", gap: 2, textAlign: "center" }}
          >
            <MaintenanceBanner
              printers={printers}
              refreshPrinters={refreshPrinters}
              onOpenPrinter={(printerId) => nav.open("printers", { printerId })}
              phone={phone}
            />
            {nav.section === pluginSection("stream") && <div
              data-testid="panels-warning"
              style={{
                ...(phone ? { fontSize: fs(14) } : { whiteSpace: "nowrap", fontSize: fs(17) }),
                pointerEvents: "none", ...ui, fontWeight: 700, color: fixed.voronRed, letterSpacing: 0.3,
              }}
            >
              WARNING Panels are reflective. Put on pants.
            </div>}
          </div>
        </div>
        {PLUGIN_SECTION.test(nav.section) && nav.section !== pluginSection(STREAM_CONTROL) ? (
          // a plugin's page fills the space under the top bar, and scrolls itself
          <div style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>
            <SectionPage section={nav.section} nav={nav} compare={compare} settings={settings} plugins={plugins} />
          </div>
        ) : (
          <div style={{ padding: gap, paddingBottom: compare.selection.length > 0 ? 80 : gap, overflow: "auto", flex: 1 }}>
            <SectionPage section={nav.section} nav={nav} compare={compare} settings={settings} plugins={plugins} />
          </div>
        )}
      </div>

      <CompareTray selection={compare.selection} onRemove={compare.remove} onClear={compare.clear} onCompare={compare.show} />

      {compare.open && (
        <Modal title="Compare 3MF files" onClose={compare.close} width={1500}>
          <DiffView left={compare.open[0]} right={compare.open[1]} />
        </Modal>
      )}
    </div>
    </EnergyPricesContext.Provider>
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
          {errorText(this.state.error)}
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
