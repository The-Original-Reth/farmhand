import { useState } from "react";
import { c } from "../theme.js";
import { pluginPageUrl } from "../api.js";
import { panelBox, primaryButton, toolButton, uiText } from "../styles.js";
import { PLUGIN_SANDBOX, usePluginFrame } from "./usePluginFrame.js";

// The Settings page's plugin part: under each added plugin's name, its own settings, as the plugin shows them (its
// manifest's settings_page: a page of the plugin's, drawn as tall as it is). A settings page with a Save of its own
// (farmhand-plugin.js onSave) gets a Save button at the right of the plugin's heading row, lit while it has changes.
// A plugin that's switched off, isn't answering, or has no settings page says so instead.
export function PluginSettings({ plugins, onOpenPage, onOpenPlugins }) {
  if (!plugins?.length) return null;
  return plugins.map((p) => <PluginSection key={p.id} plugin={p} onOpenPage={onOpenPage} onOpenPlugins={onOpenPlugins} />);
}

// A heading on the Settings page: "Farmhand", then each plugin's name; `right`: what's at the right of the same row
export function SettingsHeading({ children, right = null }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, paddingBottom: 6, borderBottom: `1px solid ${c.border}`, minHeight: 32 }}>
      <div style={uiText(18, c.heading, { fontWeight: 700, flex: 1 })}>{children}</div>
      {right}
    </div>
  );
}

function PluginSection({ plugin, onOpenPage, onOpenPlugins }) {
  const frame = usePluginFrame();
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState(null); // { ok, text }: what the plugin answered to its Save
  const shown = plugin.enabled && plugin.health.state !== "not_answering" && !!plugin.settingsPage;
  const save = async () => {
    setBusy(true);
    setSaid(null);
    try {
      setSaid(await frame.save());
    } finally {
      setBusy(false);
    }
  };
  // beside the button: a failed save's reason (until the next try), else "Not saved yet" while there are changes, else
  // what the last save said
  const [text, tone] = busy ? ["", c.textFaint]
    : said && !said.ok ? [said.text || "Couldn't save.", c.danger]
    : frame.changed ? ["Not saved yet", c.amber]
    : said ? [said.text || "Saved.", c.green]
    : ["", c.textFaint];
  const right = shown && frame.saves && (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <span data-testid={`settings-plugin-said-${plugin.id}`} style={uiText(12, tone, { maxWidth: 360, textAlign: "right", lineHeight: 1.4 })}>{text}</span>
      <button data-testid={`settings-plugin-save-${plugin.id}`} onClick={save} disabled={busy || !frame.changed} style={primaryButton(busy || !frame.changed)}>
        {busy ? "Saving…" : "Save"}
      </button>
    </div>
  );
  return (
    <section data-testid={`settings-plugin-${plugin.id}`} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <SettingsHeading right={right}>{plugin.name}</SettingsHeading>
      {shown ? <SettingsFrame plugin={plugin} frame={frame} /> : <NoSettings plugin={plugin} onOpenPage={onOpenPage} onOpenPlugins={onOpenPlugins} />}
    </section>
  );
}

function NoSettings({ plugin, onOpenPage, onOpenPlugins }) {
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
  return note(`${plugin.name} has no settings to show here.`,
    plugin.page && <button onClick={() => onOpenPage(plugin.id)} style={toolButton(12)}>Open its page</button>);
}

function SettingsFrame({ plugin, frame }) {
  return (
    <iframe
      ref={frame.frame}
      title={`${plugin.name} settings`}
      src={pluginPageUrl(plugin.id, plugin.settingsPage)}
      onLoad={frame.onLoad}
      sandbox={PLUGIN_SANDBOX}
      style={{ display: "block", width: "100%", height: frame.height ?? 160, border: "none", background: "transparent" }}
    />
  );
}
