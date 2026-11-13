import { c } from "../theme.js";
import { pluginPageUrl } from "../api.js";
import { panelBox, toolButton, uiText } from "../styles.js";
import { PLUGIN_SANDBOX, usePluginFrame } from "./usePluginFrame.js";

// The Settings page's plugin part: under each added plugin's name, its own settings, as the plugin shows them (its
// manifest's settings_page: a page of the plugin's, drawn as tall as it is). A plugin that's switched off, isn't
// answering, or has no settings page says so instead.
export function PluginSettings({ plugins, onOpenPage, onOpenPlugins }) {
  if (!plugins?.length) return null;
  return plugins.map((p) => (
    <section key={p.id} data-testid={`settings-plugin-${p.id}`} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <SettingsHeading>{p.name}</SettingsHeading>
      <PluginSettingsBody plugin={p} onOpenPage={onOpenPage} onOpenPlugins={onOpenPlugins} />
    </section>
  ));
}

// A heading on the Settings page: "Farmhand", then each plugin's name
export function SettingsHeading({ children }) {
  return (
    <div style={uiText(18, c.heading, { fontWeight: 700, paddingBottom: 6, borderBottom: `1px solid ${c.border}` })}>{children}</div>
  );
}

function PluginSettingsBody({ plugin, onOpenPage, onOpenPlugins }) {
  const note = (text, action) => (
    <div style={panelBox({ padding: 16, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" })}>
      <div style={uiText(13, c.textMuted, { lineHeight: 1.6, flex: "1 1 300px" })}>{text}</div>
      {action}
    </div>
  );
  if (!plugin.enabled) {
    return note(`${plugin.name} is switched off, so its settings aren't shown.`, <button onClick={onOpenPlugins} style={toolButton(12)}>Open the Plugins page</button>);
  }
  if (plugin.health.state === "not_answering") {
    return note(plugin.health.lastError || `${plugin.name} isn't answering, so its settings can't be shown.`,
      <button onClick={onOpenPlugins} style={toolButton(12)}>Open the Plugins page</button>);
  }
  if (!plugin.settingsPage) {
    return note(`${plugin.name} has no settings to show here.`,
      plugin.page && <button onClick={() => onOpenPage(plugin.id)} style={toolButton(12)}>Open its page</button>);
  }
  return <SettingsFrame plugin={plugin} />;
}

function SettingsFrame({ plugin }) {
  const { frame, onLoad, height } = usePluginFrame();
  return (
    <iframe
      ref={frame}
      title={`${plugin.name} settings`}
      src={pluginPageUrl(plugin.id, plugin.settingsPage)}
      onLoad={onLoad}
      sandbox={PLUGIN_SANDBOX}
      style={{ display: "block", width: "100%", height: height ?? 160, border: "none", background: "transparent" }}
    />
  );
}
