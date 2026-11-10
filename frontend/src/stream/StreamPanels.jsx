import { useState } from "react";
import { c } from "../theme.js";
import { cancelButton, fieldBox, headerButton, linkButton, monoText, panelBox, uiText } from "../styles.js";
import { saveYouTubeClient, youtubeApply, youtubeSignIn, youtubeSignOut } from "../api.js";

// The Stream page's panels for the resolution and taking turns, and the YouTube broadcast's title and description.

const panel = () => panelBox({ padding: 16, display: "flex", flexDirection: "column", gap: 12 });
const heading = uiText(14, c.heading, { fontWeight: 600 });
const help = uiText(12, c.textFaint, { lineHeight: 1.5 });
const seconds = (v) => (v === "" || v == null ? "" : Number(v));

// The whole grid all the time, or taking turns: the grid for secondsAll (0: never), then each camera on its own for
// secondsEach, in square order. `count`: how many cameras are in the grid.
// `shown`: the settings as changed on the page; `change(what)` changes them (saved with the page's Save).
// (The resolution is chosen above the preview; what it costs the computer is said here.)
export function LayoutPanel({ shown, count, change }) {
  const cycle = shown.layout === "cycle";
  const all = Number(shown.secondsAll) || 0;
  const each = Number(shown.secondsEach) || 0;
  const round = all + count * each;
  const numberBox = { ...fieldBox(), padding: "5px 8px", width: 80 };
  return (
    <div data-testid="stream-layout-panel" style={panel()}>
      <div style={heading}>Layout</div>
      {shown.resolution !== "720p" && (
        <div style={help}>
          {shown.resolution === "1080p"
            ? "1080p is sharp, and fine on a PC or the Proxmox container; on a Raspberry Pi, 720p is safer with several cameras."
            : "2K is the sharpest, and the most work for the computer: best on a PC or the Proxmox container."}
        </div>
      )}
      <label style={uiText(13, c.textPrimary, { display: "flex", alignItems: "center", gap: 8 })}>
        <input type="radio" name="stream-layout" checked={!cycle} onChange={() => change({ layout: "grid" })} />
        The whole grid, all the time
      </label>
      <label style={uiText(13, c.textPrimary, { display: "flex", alignItems: "center", gap: 8 })}>
        <input data-testid="stream-cycle" type="radio" name="stream-layout" checked={cycle} onChange={() => change({ layout: "cycle" })} />
        Take turns: the whole grid, then each camera on its own, round and round
      </label>
      {cycle && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, paddingLeft: 24 }}>
          <label style={uiText(12, c.textMuted, { display: "flex", alignItems: "center", gap: 8 })}>
            <span style={{ width: 150 }}>Stay on the whole grid</span>
            <input
              data-testid="stream-seconds-all" type="number" min={0} max={3600} value={shown.secondsAll}
              onChange={(e) => change({ secondsAll: seconds(e.target.value) })} style={numberBox}
            />
            seconds <span style={uiText(11, c.textFaint)}>(0: never)</span>
          </label>
          <label style={uiText(12, c.textMuted, { display: "flex", alignItems: "center", gap: 8 })}>
            <span style={{ width: 150 }}>Stay on each camera</span>
            <input
              data-testid="stream-seconds-each" type="number" min={3} max={3600} value={shown.secondsEach}
              onChange={(e) => change({ secondsEach: seconds(e.target.value) })} style={numberBox}
            />
            seconds
          </label>
          <div style={help}>
            {count > 1
              ? `One round takes ${round >= 120 ? `${Math.floor(round / 60)} min ${round % 60} s` : `${round} s`}${all ? `: the whole grid for ${all} s, then each of the ${count} cameras for ${each} s.` : `: each of the ${count} cameras for ${each} s.`}`
              : "With one camera there's nothing to take turns with: the grid is shown all the time."}
          </div>
        </div>
      )}
    </div>
  );
}

// The YouTube broadcast's own title and description (saved with the page's Save; set on YouTube once the broadcast
// starts, or straight away while live), and signing Farmhand in to the channel, which setting them needs.
export function YouTubeTextPanel({ shown, change, status }) {
  const title = status.title;
  return (
    <div data-testid="stream-youtube-panel" style={panel()}>
      <div style={heading}>YouTube title and description</div>
      <label style={uiText(12, c.textMuted, { display: "flex", flexDirection: "column", gap: 4 })}>
        <span>
          Title <span style={uiText(11, c.textFaint)}>{shown.title.length}/100</span>
        </span>
        <input
          data-testid="stream-title" value={shown.title} maxLength={100} onChange={(e) => change({ title: e.target.value })}
          placeholder="Left empty, YouTube's own title stays" style={{ ...fieldBox(), padding: "6px 8px" }}
        />
      </label>
      <label style={uiText(12, c.textMuted, { display: "flex", flexDirection: "column", gap: 4 })}>
        Description
        <textarea
          data-testid="stream-description" value={shown.description} maxLength={5000} rows={4} onChange={(e) => change({ description: e.target.value })}
          placeholder="Left empty, YouTube's own description stays" style={{ ...fieldBox(), padding: "6px 8px", resize: "vertical", lineHeight: 1.5 }}
        />
      </label>
      {title && (
        <div data-testid="stream-title-status" style={uiText(12, title.state === "failed" ? c.danger : title.state === "done" ? c.green : c.amber, { lineHeight: 1.5 })}>
          {title.message}
        </div>
      )}
      {!title && <div style={help}>Set on the YouTube broadcast once it starts; needs the YouTube account below signed in.</div>}
    </div>
  );
}

// Signing Farmhand in to the YouTube channel, which setting the title and description needs; while live, setting them
// again straight away.
export function YouTubeAccountPanel({ youtube, status, ask, busy }) {
  const [clientId, setClientId] = useState("");
  const [secret, setSecret] = useState("");
  const [editingClient, setEditingClient] = useState(false);
  const showClientForm = !youtube.clientSet || editingClient;
  const saveClient = () =>
    ask("youtube", () => saveYouTubeClient({ clientId: clientId.trim() || youtube.clientId, clientSecret: secret.trim() })).then(
      (p) => p && (setClientId(""), setSecret(""), setEditingClient(false)),
    );
  return (
    <div data-testid="stream-youtube-account" style={panel()}>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={heading}>YouTube account</div>
        {youtube.signedIn ? (
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span style={uiText(13, c.green, { flex: 1 })}>Signed in{youtube.channel ? ` as ${youtube.channel}` : ""}</span>
            {status.live && (
              <button type="button" data-testid="stream-youtube-apply" onClick={() => ask("youtube", youtubeApply)} disabled={!!busy} style={headerButton()}>
                {busy === "youtube" ? "Setting…" : "Set title on YouTube now"}
              </button>
            )}
            <button type="button" data-testid="stream-youtube-sign-out" onClick={() => ask("youtube", () => youtubeSignOut(false))} disabled={!!busy} style={headerButton()}>
              Sign out
            </button>
          </div>
        ) : youtube.signingIn ? (
          <div data-testid="stream-youtube-code" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={uiText(13, c.textPrimary, { lineHeight: 1.6 })}>
              Open{" "}
              <a href={youtube.signingIn.verificationUrl} target="_blank" rel="noreferrer" style={{ color: c.amber }}>
                {youtube.signingIn.verificationUrl.replace(/^https?:\/\//, "")}
              </a>{" "}
              on any computer or phone, sign in to the Google account that owns the channel, and enter this code:
            </div>
            <div style={monoText(22, c.heading, { letterSpacing: 2 })}>{youtube.signingIn.userCode}</div>
            <div style={help}>This page notices by itself once you've entered it.</div>
          </div>
        ) : showClientForm ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={help}>
              Setting the title needs Farmhand signed in to your channel, once. In{" "}
              <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noreferrer" style={{ color: c.amber }}>Google Cloud</a>: make a
              project, turn on the YouTube Data API v3, set the OAuth consent screen to “In production” (a test one stops working after 7
              days), then Create credentials → OAuth client ID → <b>TVs and Limited Input devices</b>. Paste its client ID and secret here.
            </div>
            <input
              data-testid="stream-youtube-client-id" value={clientId} onChange={(e) => setClientId(e.target.value)} autoComplete="off"
              placeholder={youtube.clientId || "Client ID (…apps.googleusercontent.com)"} style={{ ...fieldBox(), padding: "6px 8px" }}
            />
            <input
              data-testid="stream-youtube-secret" type="password" value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="off"
              placeholder={youtube.clientSet ? "Client secret (saved; type to replace)" : "Client secret"} style={{ ...fieldBox(), padding: "6px 8px" }}
            />
            <div style={{ display: "flex", gap: 8 }}>
              <button
                type="button" data-testid="stream-youtube-save-client" onClick={saveClient} disabled={!!busy || (!clientId.trim() && !youtube.clientSet)}
                style={headerButton()}
              >
                {busy === "youtube" ? "Saving…" : "Save client"}
              </button>
              {editingClient && (
                <button type="button" onClick={() => setEditingClient(false)} style={cancelButton()}>
                  Cancel
                </button>
              )}
            </div>
          </div>
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span style={uiText(12, c.textMuted, { flex: 1, minWidth: 200, wordBreak: "break-all" })}>Client: {youtube.clientId}</span>
            <button type="button" onClick={() => setEditingClient(true)} style={linkButton(12)}>
              Change
            </button>
            <button type="button" data-testid="stream-youtube-sign-in" onClick={() => ask("youtube", youtubeSignIn)} disabled={!!busy} style={headerButton()}>
              {busy === "youtube" ? "Asking Google…" : "Sign in to YouTube"}
            </button>
          </div>
        )}
        {youtube.error && <div style={uiText(12, c.danger, { lineHeight: 1.5 })}>{youtube.error}</div>}
      </div>
    </div>
  );
}
