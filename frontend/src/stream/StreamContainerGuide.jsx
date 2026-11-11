import { useState } from "react";
import { Check, ChevronDown, ChevronRight, Copy, Download } from "lucide-react";
import { c, fs, ui } from "../theme.js";
import { foldHeading, monoText, toolButton, uiText } from "../styles.js";
import { errorText } from "../api.js";
import { heading, help, panel } from "./streamStyles.js";
// The Stream plugin's compose file, the same as plugins/stream/docker-compose.yml (its tests check the two match)
import compose from "./plugin/docker-compose.yml?raw";

// How to run the stream in a container of its own (the Stream plugin), so a Farmhand update, restart or crash never
// stops it: the steps and the docker-compose file to start it with. Folded away until opened.

const code = () => monoText(12, c.heading, {
  background: c.panelAlt, border: `1px solid ${c.border}`, borderRadius: 4, padding: "7px 10px", margin: 0,
  whiteSpace: "pre", overflowX: "auto",
});

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
    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
      <pre style={{ ...code(), flex: 1, minWidth: 0 }}>{text}</pre>
      <CopyButton text={text} />
    </div>
  );
}

const download = () => {
  const url = URL.createObjectURL(new Blob([compose], { type: "text/yaml" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "docker-compose.yml";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};

// the same file on GitHub, for fetching it straight onto the plugin's machine
const RAW = "https://raw.githubusercontent.com/The-Original-Reth/farmhand/main/plugins/stream/docker-compose.yml";

const step = uiText(13, c.textPrimary, { lineHeight: 1.5 });

export function StreamContainerGuide() {
  const [open, setOpen] = useState(false);
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <div data-testid="stream-container-guide" style={panel()}>
      <div style={foldHeading(false)}>
        <button
          type="button" data-testid="stream-container-guide-toggle" onClick={() => setOpen(!open)}
          style={{ ...heading, background: "none", border: "none", padding: 0, cursor: "pointer", display: "flex", alignItems: "center", gap: 6 }}
        >
          <Chevron size={15} /> Run the stream in its own container
        </button>
      </div>
      <div style={help}>
        The Stream plugin is this page in a Docker container of its own, on this machine or another one, so a Farmhand
        update, restart or crash never stops the stream. A camera that stops shows "Camera down" while the others carry on.
      </div>
      {open && (
        <ol style={{ ...step, margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 12 }}>
          <li>
            On a machine with Docker and git that reaches the cameras and Farmhand, make a folder for it:
            <Command text="sudo mkdir -p /opt/farmhand-stream && cd /opt/farmhand-stream" />
          </li>
          <li>
            Put the docker-compose file below in that folder as <code style={monoText(12, c.heading)}>docker-compose.yml</code>{" "}
            (Download, or fetch it there):
            <Command text={`sudo curl -fsSLo docker-compose.yml ${RAW}`} />
            Change <code style={monoText(12, c.heading)}>./media</code> to the stream folder this page uses, mounted on
            that machine, so the pictures, slideshows and music are found. With an NVIDIA card, remove the # signs
            in its part.
          </li>
          <li>
            Build and start it. Docker builds it straight from Farmhand's GitHub, which takes a few minutes the first
            time:
            <Command text="sudo docker compose up -d --build" />
          </li>
          <li>
            In Farmhand, open <b>Plugins</b> (under Settings), add <code style={monoText(12, c.heading)}>http://&lt;that machine&gt;:8080</code> and
            say yes to what it asks for. Farmhand shows <code style={monoText(12, c.heading)}>FARMHAND_URL</code> and{" "}
            <code style={monoText(12, c.heading)}>FARMHAND_TOKEN</code> once: put both lines in a file{" "}
            <code style={monoText(12, c.heading)}>stream.env</code> in the same folder, then start it again:
            <Command text="sudo docker compose up -d --force-recreate" />
          </li>
          <li>
            <b>Stream</b> appears in Farmhand's menu with the plugin's page. The first time, it brings over this page's
            settings, layouts, stream key and YouTube sign-in. Go live from there, and stop the stream here first:
            never go live on both with the same stream key.
          </li>
        </ol>
      )}
      {open && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <div style={uiText(13, c.heading, { fontWeight: 600, flex: 1 })}>docker-compose.yml</div>
            <CopyButton text={compose} testId="stream-compose-copy" />
            <button type="button" data-testid="stream-compose-download" onClick={download} style={{ ...toolButton(12), ...ui, fontSize: fs(12) }}>
              <Download size={13} /> Download
            </button>
          </div>
          <pre data-testid="stream-compose" style={{ ...code(), maxHeight: 360 }}>{compose}</pre>
        </div>
      )}
    </div>
  );
}
