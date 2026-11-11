import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { c } from "../theme.js";
import { cancelButton, fieldBox, headerButton, linkButton, monoText, uiText } from "../styles.js";
import { heading, help } from "./streamStyles.js";
import { saveYouTubeClient, youtubeApply, youtubeSignIn, youtubeSignOut } from "../api.js";

// The YouTube account Farmhand signs in to, in the YouTube settings window: the Google client it signs in with (its ID
// and secret hidden until the eye beside them is clicked), the sign-in with a code, and a link to the step-by-step guide.

// A client ID or secret: dots until the eye next to it is clicked. `testid`: the field's; its eye's is `${testid}-show`.
function HiddenField({ testid, value, onChange, placeholder }) {
  const [shown, setShown] = useState(false);
  return (
    <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
      <input
        data-testid={testid} type={shown ? "text" : "password"} value={value} onChange={(e) => onChange(e.target.value)} autoComplete="off"
        placeholder={placeholder} style={{ ...fieldBox(), padding: "6px 8px", flex: 1, minWidth: 0 }}
      />
      <button
        type="button" data-testid={`${testid}-show`} onClick={() => setShown(!shown)} aria-label={shown ? "Hide" : "Show"} title={shown ? "Hide it" : "Show it"}
        style={{ ...headerButton(), padding: "0 7px" }}
      >
        {shown ? <EyeOff size={14} /> : <Eye size={14} />}
      </button>
    </div>
  );
}

// The saved client ID, as dots until the eye is clicked
function HiddenText({ value }) {
  const [shown, setShown] = useState(false);
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, flex: 1, minWidth: 200 }}>
      <span data-testid="stream-youtube-client-shown" style={uiText(12, c.textMuted, { wordBreak: "break-all" })}>
        Client: {shown ? value : "•".repeat(Math.min(24, (value || "").length || 12))}
      </span>
      <button
        type="button" data-testid="stream-youtube-client-show" onClick={() => setShown(!shown)} aria-label={shown ? "Hide" : "Show"} title={shown ? "Hide it" : "Show it"}
        style={{ ...headerButton(), padding: "0 7px" }}
      >
        {shown ? <EyeOff size={14} /> : <Eye size={14} />}
      </button>
    </span>
  );
}

// The step-by-step guide to connecting the channel, on a page of its own (YouTubeGuide.jsx), in a new tab
const GUIDE_URL = "/help/youtube";
const GuideLink = () => (
  <a data-testid="stream-youtube-guide" href={GUIDE_URL} target="_blank" rel="noreferrer" style={uiText(12, c.amber, { textDecoration: "underline" })}>
    How to connect your YouTube channel, step by step
  </a>
);

// Signing Farmhand in to the YouTube channel, so it makes and changes the broadcast itself; while live, Send to YouTube
// again puts the saved settings on the broadcast once more.
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
    <div data-testid="stream-youtube-account">
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
          <div style={heading}>YouTube account</div>
          <GuideLink />
        </div>
        {youtube.signedIn ? (
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span style={uiText(13, c.green, { flex: 1 })}>Signed in{youtube.channel ? ` as ${youtube.channel}` : ""}</span>
            {status.live && (
              <button type="button" data-testid="stream-youtube-apply" onClick={() => ask("youtube", youtubeApply)} disabled={!!busy} style={headerButton()}>
                {busy === "youtube" ? "Setting…" : "Send to YouTube again"}
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
              Setting the title needs Farmhand signed in to your channel, once: make a small app in Google Cloud (a{" "}
              <b>TVs and Limited Input devices</b> client) and paste its client ID and secret here. The guide above goes through it
              step by step.
            </div>
            <HiddenField
              testid="stream-youtube-client-id" value={clientId} onChange={setClientId}
              placeholder={youtube.clientSet ? "Client ID (saved; type to replace)" : "Client ID (…apps.googleusercontent.com)"}
            />
            <HiddenField
              testid="stream-youtube-secret" value={secret} onChange={setSecret}
              placeholder={youtube.clientSet ? "Client secret (saved; type to replace)" : "Client secret"}
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
            <HiddenText value={youtube.clientId} />
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
