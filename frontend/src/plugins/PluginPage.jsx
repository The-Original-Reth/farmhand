import { c } from "../theme.js";
import { pluginPageUrl } from "../api.js";
import { panelBox, primaryButton, toolButton, uiText } from "../styles.js";
import { fmtWhen } from "../lib/format.js";
import { PLUGIN_SANDBOX, usePluginFrame } from "./usePluginFrame.js";

// A plugin's own page, filling the space under Farmhand's top bar: an iframe on /plugins/<id>/, which the web server
// passes on to the plugin wherever it runs. It's given Farmhand's colours once its farmhand-plugin.js says it's ready,
// and again whenever they change. A plugin that isn't answering shows why instead.
export function PluginPage({ pluginId, plugin, loaded, onRetry, onOpenPlugins }) {
  const { frame, onLoad } = usePluginFrame();

  if (!plugin) {
    return (
      <Notice title={loaded ? "There's no such plugin" : "Loading the plugin…"}>
        {loaded && (
          <>
            <div>No plugin called “{pluginId}” is added to Farmhand, or it's switched off.</div>
            <button onClick={onOpenPlugins} style={{ ...primaryButton(), marginTop: 14 }}>Open the Plugins page</button>
          </>
        )}
      </Notice>
    );
  }
  if (plugin.health.state === "not_answering") {
    return (
      <Notice title="This plugin isn't running">
        <div>{plugin.health.lastError || `${plugin.name} didn't answer Farmhand.`}</div>
        <div style={uiText(12, c.textFaint, { marginTop: 8 })}>
          Last answered: {fmtWhen(plugin.health.lastSeenAt, "never")}. Farmhand asks again every 30 seconds. Its address is{" "}
          {plugin.address}: start its container there.
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
          <button onClick={onRetry} style={primaryButton()}>Try again</button>
          <button onClick={onOpenPlugins} style={toolButton(13)}>Open the Plugins page</button>
        </div>
      </Notice>
    );
  }
  return (
    <iframe
      ref={frame}
      key={plugin.id}
      title={plugin.name}
      src={pluginPageUrl(plugin.id, plugin.page?.path || "/")}
      onLoad={onLoad}
      sandbox={PLUGIN_SANDBOX}
      style={{ display: "block", width: "100%", height: "100%", border: "none", background: c.bg }}
    />
  );
}

function Notice({ title, children }) {
  return (
    <div style={{ padding: 24 }}>
      <div style={panelBox({ padding: 20, maxWidth: 640 })}>
        <div style={uiText(16, c.heading, { fontWeight: 600, marginBottom: 8 })}>{title}</div>
        <div style={uiText(13, c.textMuted, { lineHeight: 1.6 })}>{children}</div>
      </div>
    </div>
  );
}
