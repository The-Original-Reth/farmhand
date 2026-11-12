import { useState } from "react";
import { Check, ChevronDown, ChevronRight, Copy, Download } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { errorText } from "../api.js";
import { foldHeading, monoText, panelBox, toolButton, uiText } from "../styles.js";
// The plugins' own compose files, the same as plugins/<id>/docker-compose.yml (each plugin's tests check they match)
import streamCompose from "./compose/stream.yml?raw";
import helloCompose from "./compose/hello.yml?raw";

// How to run a plugin in a Docker container of its own, on this machine or another one: the steps, for any plugin.
// The plugins in Farmhand's own repository (plugins/<id>/) that have a compose file get theirs filled in: their folder,
// the line fetching the file from GitHub, their env file and port, their own notes, and the file itself to copy or
// download. Folded away until opened.

const RAW = (id) => `https://raw.githubusercontent.com/The-Original-Reth/farmhand/main/plugins/${id}/docker-compose.yml`;
const kbd = (text) => <code style={monoText(12, c.heading)}>{text}</code>;

// plugin id -> what the guide fills in for it. Its folder is /opt/farmhand-<id> and its env file <id>.env, as its
// compose file says.
export const GUIDED_PLUGINS = {
  stream: {
    name: "Stream",
    port: 8080,
    compose: streamCompose,
    notes: (
      <>
        <div>
          <b>The stream folder.</b> Its pictures, slideshows and music are in the stream folder on the NAS. Mount that
          share on the plugin's machine and, in the compose file, change {kbd("./media")} to that folder (for example{" "}
          {kbd("- /mnt/stream:/media")}), so the plugin finds them.
        </div>
        <div>
          <b>An NVIDIA card.</b> To compress the stream on the card and leave the processor for the cameras, remove the #
          signs in its NVIDIA part. The machine needs the NVIDIA driver's libraries (on a Proxmox container, at the host's
          driver version).
        </div>
        <div>
          Once it's added, <b>Stream</b> appears in Farmhand's menu after Monitor. The first time, its page offers to bring
          over the Stream page set-up this Farmhand saved before Stream became a plugin (its settings, layouts, stream key
          and YouTube sign-in).
        </div>
      </>
    ),
  },
  hello: {
    name: "Hello",
    port: 8080,
    compose: helloCompose,
    notes: (
      <div>
        Hello is the example plugin: each printer and how far along its print is. Copy its folder in Farmhand's
        repository ({kbd("plugins/hello")}) to start a plugin of your own.
      </div>
    ),
  },
};
const OTHER = "other";

const code = () => monoText(12, c.heading, {
  background: c.panelAlt, border: `1px solid ${c.border}`, borderRadius: 4, padding: "7px 10px", margin: 0,
  whiteSpace: "pre", overflowX: "auto",
});
const step = uiText(13, c.textPrimary, { lineHeight: 1.5 });

function CopyButton({ text, testId }) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState(null);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text); // only on https or this computer's own address
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (e) {
      setError(`Couldn't copy it (${errorText(e)}): select it and copy it by hand.`);
    }
  };
  return (
    <>
      <button type="button" data-testid={testId} onClick={copy} style={{ ...toolButton(12), ...ui, fontSize: fs(12) }}>
        {copied ? <Check size={13} /> : <Copy size={13} />} {copied ? "Copied" : "Copy"}
      </button>
      {error && <span style={uiText(12, c.amber)}>{error}</span>}
    </>
  );
}

// a command to type on the plugin's machine, with Copy beside it
function Command({ text }) {
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 4 }}>
      <pre style={{ ...code(), flex: 1, minWidth: 0 }}>{text}</pre>
      <CopyButton text={text} />
    </div>
  );
}

const download = (text) => {
  const url = URL.createObjectURL(new Blob([text], { type: "text/yaml" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "docker-compose.yml";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};

export function RunPluginGuide() {
  const [open, setOpen] = useState(false);
  const [chosen, setChosen] = useState("stream");
  const Chevron = open ? ChevronDown : ChevronRight;
  const plugin = GUIDED_PLUGINS[chosen]; // undefined: another plugin, the steps for any
  const folder = plugin ? `/opt/farmhand-${chosen}` : "/opt/farmhand-<name>";
  const envFile = plugin ? `${chosen}.env` : null;
  const address = `http://<that machine>:${plugin ? plugin.port : "<its port>"}`;
  const choice = (key, label) => (
    <button
      key={key}
      type="button"
      data-testid={`run-plugin-${key}`}
      aria-pressed={chosen === key}
      onClick={() => setChosen(key)}
      style={toolButton(12, chosen === key ? { color: c.heading, border: `1px solid ${c.amber}`, background: c.panelAlt } : undefined)}
    >
      {label}
    </button>
  );

  return (
    <div data-testid="run-plugin-guide" style={panelBox({ padding: 16, display: "flex", flexDirection: "column", gap: 12 })}>
      <div style={foldHeading(false)}>
        <button
          type="button" data-testid="run-plugin-guide-toggle" onClick={() => setOpen(!open)}
          style={{ ...uiText(14, c.heading, { fontWeight: 600 }), background: "none", border: "none", padding: 0, cursor: "pointer", display: "flex", alignItems: "center", gap: 6 }}
        >
          <Chevron size={15} /> Run a plugin in its own container
        </button>
      </div>
      <div style={uiText(12, c.textFaint, { lineHeight: 1.5 })}>
        Each plugin runs in a Docker container of its own, on this machine or another one on the farm's network, so a
        Farmhand update, restart or crash never stops it. These are the steps to start one with docker compose.
      </div>
      {open && (
        <>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <span style={uiText(13, c.textMuted)}>Which plugin:</span>
            {Object.entries(GUIDED_PLUGINS).map(([key, p]) => choice(key, p.name))}
            {choice(OTHER, "Another plugin")}
          </div>
          <ol style={{ ...step, margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 12 }}>
            <li>
              On a machine with Docker and git that reaches Farmhand (and the cameras, for a plugin that uses them), make a
              folder for it:
              <Command text={`sudo mkdir -p ${folder} && cd ${folder}`} />
            </li>
            <li>
              {plugin ? (
                <>
                  Put {plugin.name}'s compose file (below) in that folder as {kbd("docker-compose.yml")}: Download it, or
                  fetch it there:
                  <Command text={`sudo curl -fsSLo docker-compose.yml ${RAW(chosen)}`} />
                </>
              ) : (
                <>Put the plugin's {kbd("docker-compose.yml")} in that folder, from the plugin's own instructions.</>
              )}
            </li>
            <li>
              Build and start it. A compose file that builds the plugin from GitHub takes a few minutes the first time:
              <Command text="sudo docker compose up -d --build" />
            </li>
            <li>
              Here, under <b>Add a plugin</b>, add {kbd(address)} and say yes to what it asks for.
              {!plugin && <> Its port is the left side of the {kbd("ports:")} line in its compose file.</>}
            </li>
            <li>
              Farmhand shows two lines once, {kbd("FARMHAND_URL=…")} and {kbd("FARMHAND_TOKEN=…")}. Put both in{" "}
              {envFile ? <>a file {kbd(envFile)}</> : <>the env file its compose file names under {kbd("env_file:")}</>}, in
              the same folder, beside {kbd("docker-compose.yml")}.
            </li>
            <li>
              Start it again, so it reads them:
              <Command text="sudo docker compose up -d --force-recreate" />
              Its page is then in Farmhand's menu (for a plugin that has one).
            </li>
          </ol>
          {plugin && (
            <div data-testid="run-plugin-notes" style={{ ...step, display: "flex", flexDirection: "column", gap: 8 }}>
              {plugin.notes}
            </div>
          )}
          {plugin && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <div style={uiText(13, c.heading, { fontWeight: 600, flex: 1 })}>{plugin.name}'s docker-compose.yml</div>
                <CopyButton text={plugin.compose} testId="run-plugin-compose-copy" />
                <button
                  type="button" data-testid="run-plugin-compose-download" onClick={() => download(plugin.compose)}
                  style={{ ...toolButton(12), ...ui, fontSize: fs(12) }}
                >
                  <Download size={13} /> Download
                </button>
              </div>
              <pre data-testid="run-plugin-compose" style={{ ...code(), maxHeight: 360 }}>{plugin.compose}</pre>
            </div>
          )}
        </>
      )}
    </div>
  );
}
