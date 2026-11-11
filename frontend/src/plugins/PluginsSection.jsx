import { useState } from "react";
import { Check, Copy, ExternalLink, KeyRound, Puzzle } from "lucide-react";
import { c, fs, mono, ui } from "../theme.js";
import { addPlugin, changePlugin, errorText, newPluginToken, pluginApiUrl, previewPlugin, removePlugin } from "../api.js";
import { cancelButton, fieldBox, monoText, panelBox, primaryButton, toolButton, uiText } from "../styles.js";
import { useAction } from "../hooks/useAction.js";
import { ConfirmDialog, Modal } from "../components/common/dialogs.jsx";
import { Badge } from "../components/common/ui.jsx";
import { fmtWhen } from "../lib/format.js";

// How a plugin is doing, as its badge says it
const STATES = {
  running: { tone: "green", label: "running" },
  not_answering: { tone: "amber", label: "not answering" },
  unknown: { tone: "muted", label: "not asked yet" },
  off: { tone: "muted", label: "switched off" },
};

// The Plugins page: the plugins added to Farmhand, how each is doing, and adding one by its address. Farmhand doesn't
// start or stop a plugin's container: that's done where it runs, by its own instructions. `plugins` comes from
// usePlugins (shared with the menu); onChanged asks for it again. onOpenPage(id) opens a plugin's page.
export function PluginsSection({ plugins, onChanged, onOpenPage }) {
  const [token, setToken] = useState(null); // { plugin, token }: shown once
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 900 }}>
      <div style={panelBox({ padding: 16 })}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
          <Puzzle size={16} color={c.amber} />
          <div style={uiText(15, c.heading)}>Plugins</div>
        </div>
        <div style={uiText(13, c.textMuted, { lineHeight: 1.6 })}>
          A plugin is a program someone wrote that adds something to Farmhand, like a live stream or a dashboard. Each
          one runs in a container of its own, on this machine or another one on the farm's network, and reads only
          what you allow it to. Farmhand doesn't start or stop plugins: start the plugin's container the way its
          instructions say, then add it here by its address.
        </div>
      </div>

      <AddPlugin onAdded={(r) => { setToken(r); onChanged(); }} />

      {plugins.length === 0 ? (
        <div style={uiText(13, c.textFaint)}>No plugins added yet.</div>
      ) : (
        plugins.map((p) => (
          <PluginCard key={p.id} plugin={p} onChanged={onChanged} onToken={setToken} onOpenPage={() => onOpenPage(p.id)} />
        ))
      )}

      {token && <TokenDialog plugin={token.plugin} token={token.token} onClose={() => setToken(null)} />}
    </div>
  );
}

// Adding a plugin: its address, a look at what it is and what it asks for, then a yes
function AddPlugin({ onAdded }) {
  const [address, setAddress] = useState("");
  const [preview, setPreview] = useState(null);
  const [granted, setGranted] = useState([]);
  const [onlyFrom, setOnlyFrom] = useState(true);
  const look = useAction();
  const adding = useAction();

  const lookAt = () =>
    look.run(async () => {
      const found = await previewPlugin(address);
      setPreview(found);
      setGranted(found.manifest.permissions);
      setOnlyFrom(true);
    });
  const add = () =>
    adding.run(async () => {
      const r = await addPlugin({ address: preview.address, permissions: granted, onlyFromAddress: onlyFrom });
      setPreview(null);
      setAddress("");
      onAdded(r);
    });
  const host = preview ? new URL(preview.address).hostname : "";

  return (
    <div style={panelBox({ padding: 16 })}>
      <div style={uiText(14, c.heading, { marginBottom: 4 })}>Add a plugin</div>
      <div style={uiText(12, c.textFaint, { marginBottom: 10, lineHeight: 1.5 })}>
        The address its container answers at, like http://192.168.10.215:8080 (or http://hello:8080 for a container
        beside Farmhand's own). Farmhand asks it what it is first; nothing is added until you say yes.
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          lookAt();
        }}
        style={{ display: "flex", gap: 8 }}
      >
        <input
          data-testid="plugin-address"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          placeholder="http://192.168.10.215:8080"
          disabled={!!preview}
          style={{ ...fieldBox(), ...mono, flex: 1, padding: "8px 10px" }}
        />
        {!preview && (
          <button type="submit" disabled={look.busy || !address.trim()} style={primaryButton(look.busy || !address.trim())}>
            {look.busy ? "Asking it…" : "Look at it"}
          </button>
        )}
      </form>
      {look.error && <div style={uiText(12, c.amber, { marginTop: 10, lineHeight: 1.5 })}>{look.error}</div>}

      {preview && (
        <div data-testid="plugin-preview" style={{ marginTop: 14, border: `1px solid ${c.borderStrong}`, borderRadius: 4, background: c.panelAlt, padding: 14 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
            <div style={uiText(15, c.heading, { fontWeight: 600 })}>{preview.manifest.name}</div>
            <span style={monoText(12, c.textFaint)}>{preview.manifest.version}</span>
            {preview.manifest.author && <span style={uiText(12, c.textFaint)}>by {preview.manifest.author}</span>}
            {preview.manifest.homepage && (
              <a href={preview.manifest.homepage} target="_blank" rel="noreferrer" style={uiText(12, c.teal)}>
                its page <ExternalLink size={11} />
              </a>
            )}
          </div>
          {preview.installed ? (
            <div style={uiText(13, c.amber, { marginTop: 10, lineHeight: 1.5 })}>
              A plugin called “{preview.manifest.id}” is added already. To add this one in its place, remove that one first.
            </div>
          ) : (
            <>
              <div style={uiText(13, c.textMuted, { marginTop: 10, marginBottom: 6 })}>
                {preview.permissionsDescribed.length ? "It asks to:" : "It doesn't ask to read anything of Farmhand's."}
              </div>
              {preview.permissionsDescribed.map(({ permission, means }) => (
                <label key={permission} style={{ display: "flex", gap: 8, alignItems: "flex-start", marginBottom: 6, cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={granted.includes(permission)}
                    onChange={(e) => setGranted((g) => (e.target.checked ? [...g, permission] : g.filter((x) => x !== permission)))}
                    style={{ marginTop: 3 }}
                  />
                  <span style={uiText(13, c.textPrimary, { lineHeight: 1.5 })}>{means}</span>
                </label>
              ))}
              {preview.permissionsDescribed.length > 0 && (
                <div style={uiText(12, c.textFaint, { marginBottom: 10, lineHeight: 1.5 })}>
                  Untick anything you'd rather it didn't see: the plugin may then not work fully. It can never change anything in Farmhand.
                </div>
              )}
              <label style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 4, cursor: "pointer" }}>
                <input type="checkbox" checked={onlyFrom} onChange={(e) => setOnlyFrom(e.target.checked)} style={{ marginTop: 3 }} />
                <span style={uiText(13, c.textPrimary, { lineHeight: 1.5 })}>
                  Only accept its token from its own address ({host}), so the token is no use to anyone else on the network
                </span>
              </label>
            </>
          )}
          {adding.error && <div style={uiText(12, c.amber, { marginTop: 10, lineHeight: 1.5 })}>{adding.error}</div>}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 12 }}>
            <button onClick={() => setPreview(null)} disabled={adding.busy} style={cancelButton(adding.busy)}>Cancel</button>
            {!preview.installed && (
              <button data-testid="plugin-add" onClick={add} disabled={adding.busy} style={primaryButton(adding.busy)}>
                {adding.busy ? "Adding…" : `Add ${preview.manifest.name}`}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// One plugin: how it's doing, where it runs, what it may read, and its buttons
function PluginCard({ plugin: p, onChanged, onToken, onOpenPage }) {
  const [asking, setAsking] = useState(null); // "token" | "remove"
  const change = useAction();
  const state = STATES[p.health.state] || STATES.unknown;
  const set = (what) => change.run(async () => { await changePlugin(p.id, what); onChanged(); });

  return (
    <div data-testid={`plugin-${p.id}`} style={panelBox({ padding: 16 })}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
        <div style={uiText(15, c.heading, { fontWeight: 600 })}>{p.name}</div>
        <span style={monoText(12, c.textFaint)}>{p.version}</span>
        <Badge tone={state.tone}>{state.label}</Badge>
        {p.needsToken && <Badge tone="amber">needs a new token</Badge>}
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          {p.page && p.enabled && (
            <button onClick={onOpenPage} style={toolButton(12)}>
              <ExternalLink size={13} /> Open its page
            </button>
          )}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "4px 12px", marginBottom: 10 }}>
        <span style={uiText(12, c.textFaint)}>Address</span>
        <span style={monoText(12, c.textPrimary, { wordBreak: "break-all" })}>{p.address}</span>
        <span style={uiText(12, c.textFaint)}>Last answered</span>
        <span style={uiText(12, c.textMuted)}>{fmtWhen(p.health.lastSeenAt, "never")}</span>
        <span style={uiText(12, c.textFaint)}>Token</span>
        <span style={uiText(12, c.textMuted)}>
          {p.needsToken
            ? "none yet: Load all settings brought this plugin back without one. Make a new token and give it to the plugin."
            : `made ${fmtWhen(p.tokenCreatedAt)}, last used ${fmtWhen(p.tokenLastUsedAt, "never")}`}
        </span>
      </div>
      {p.health.state === "not_answering" && p.health.lastError && (
        <div style={uiText(12, c.amber, { marginBottom: 10, lineHeight: 1.5 })}>{p.health.lastError}</div>
      )}

      <div style={uiText(12, c.textFaint, { marginBottom: 4 })}>It may:</div>
      {p.permissionsDescribed.length ? (
        <ul style={{ margin: "0 0 12px", paddingLeft: 20 }}>
          {p.permissionsDescribed.map(({ permission, means }) => (
            <li key={permission} style={uiText(13, c.textMuted, { lineHeight: 1.5 })}>{means}</li>
          ))}
        </ul>
      ) : (
        <div style={uiText(13, c.textMuted, { marginBottom: 12 })}>read nothing of Farmhand's</div>
      )}

      <label style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12, cursor: "pointer" }}>
        <input
          type="checkbox"
          checked={p.onlyFromAddress}
          disabled={change.busy}
          onChange={(e) => set({ onlyFromAddress: e.target.checked })}
        />
        <span style={uiText(13, c.textPrimary)}>Only accept its token from its own address</span>
      </label>

      {change.error && <div style={uiText(12, c.amber, { marginBottom: 10 })}>{change.error}</div>}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button data-testid={`plugin-${p.id}-switch`} onClick={() => set({ enabled: !p.enabled })} disabled={change.busy} style={toolButton(12)}>
          {p.enabled ? "Switch off" : "Switch on"}
        </button>
        <button onClick={() => setAsking("token")} style={toolButton(12)}>
          <KeyRound size={13} /> New token…
        </button>
        <button onClick={() => setAsking("remove")} style={toolButton(12, { color: c.danger, borderColor: c.danger })}>
          Remove…
        </button>
      </div>
      {!p.enabled && (
        <div style={uiText(12, c.textFaint, { marginTop: 8 })}>
          Switched off: Farmhand refuses its token and its page is out of the menu. Its container keeps running until it's stopped where it runs.
        </div>
      )}

      {asking === "token" && (
        <ConfirmDialog
          title={`A new token for ${p.name}`}
          confirmLabel="Make a new token"
          tone="amber"
          onClose={() => setAsking(null)}
          onConfirm={async () => {
            const r = await newPluginToken(p.id);
            onChanged();
            onToken(r);
          }}
        >
          {p.needsToken
            ? `${p.name} has no token yet. Farmhand makes one and shows it once, to give to the plugin.`
            : `The token ${p.name} has now stops working at once. Farmhand shows the new one once: give it to the plugin and restart its container.`}
        </ConfirmDialog>
      )}
      {asking === "remove" && (
        <ConfirmDialog
          title={`Remove ${p.name}?`}
          confirmLabel="Remove"
          onClose={() => setAsking(null)}
          onConfirm={async () => {
            await removePlugin(p.id);
            onChanged();
          }}
        >
          {p.name} is taken off Farmhand: its token stops working and its page leaves the menu. Its container, and
          whatever it keeps in its own storage, stay where it runs: stop and delete it there if you don't want it.
        </ConfirmDialog>
      )}
    </div>
  );
}

// The token, shown once, with how to give it to the plugin
function TokenDialog({ plugin, token, onClose }) {
  const url = pluginApiUrl();
  const snippet = `    environment:\n      FARMHAND_URL: ${url}\n      FARMHAND_TOKEN: ${token}`;
  return (
    <Modal title={`Give ${plugin.name} its token`} onClose={onClose} width={640} closeOnBackdrop={false}>
      <div style={uiText(13, c.textMuted, { lineHeight: 1.6, marginBottom: 12 })}>
        {plugin.name} needs these two settings to read Farmhand. Give them to its container as environment variables
        (in its docker-compose.yml, under <span style={monoText(12, c.textPrimary)}>environment:</span>, as below), then
        restart it.
      </div>
      <Copyable label="FARMHAND_URL" value={url} />
      <Copyable label="FARMHAND_TOKEN" value={token} testId="plugin-token" />
      <div style={uiText(12, c.textFaint, { margin: "4px 0 6px" })}>In its docker-compose.yml:</div>
      <pre style={monoText(12, c.textPrimary, { background: c.panelAlt, border: `1px solid ${c.border}`, borderRadius: 4, padding: 10, margin: 0, overflowX: "auto" })}>
        {snippet}
      </pre>
      <div style={uiText(12, c.amber, { lineHeight: 1.5, marginTop: 12 })}>
        This is the only time Farmhand shows this token: it keeps only a scrambled copy. If it's lost, make a new one on
        this page. A plugin running in Docker beside Farmhand can use http://api:4545/plugin-api/v1 as its FARMHAND_URL.
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 14 }}>
        <button onClick={onClose} style={primaryButton()}>Done</button>
      </div>
    </Modal>
  );
}

function Copyable({ label, value, testId }) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState(null);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (e) {
      setError(`Couldn't copy it (${errorText(e)}): select it and copy it by hand.`);
    }
  };
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={uiText(12, c.textFaint, { marginBottom: 4 })}>{label}</div>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <div data-testid={testId} style={monoText(12, c.heading, { flex: 1, background: c.panelAlt, border: `1px solid ${c.border}`, borderRadius: 4, padding: "7px 10px", wordBreak: "break-all", userSelect: "all" })}>
          {value}
        </div>
        <button onClick={copy} style={{ ...toolButton(12), ...ui, fontSize: fs(12) }}>
          {copied ? <Check size={13} /> : <Copy size={13} />} {copied ? "Copied" : "Copy"}
        </button>
      </div>
      {error && <div style={uiText(12, c.amber, { marginTop: 4 })}>{error}</div>}
    </div>
  );
}
