import { useEffect, useState } from "react";
import { Eye, EyeOff, Youtube } from "lucide-react";
import { c } from "../theme.js";
import { cancelButton, fieldBox, headerButton, primaryButton, uiText } from "../styles.js";
import { errorText, getStream, saveStream } from "../api.js";
import { help, label12 } from "./streamStyles.js";
import { YouTubeAccountPanel } from "./StreamPanels.jsx";

// Everything YouTube, in a browser window of its own (/youtube-settings; YouTubeSettingsButton opens it), so it can be
// moved anywhere, another screen included, and left open: the video's title, description, tags and category; who can
// watch it; how the stream behaves on YouTube; the stream key; and the YouTube account Farmhand signs in to. Save saves
// just these (changes on the Stream page not saved yet stay as they are) and tells the Stream page, wherever it's open,
// to show them. Saved settings go on the next broadcast; while live, they change the one going out straight away.

export const WINDOW_PATH = "/youtube-settings";
const WINDOW_NAME = "farmhand-youtube-settings";
// the Stream page hears the window's saves on this (any tab or window of this Farmhand, in this browser)
export const STREAM_CHANNEL = "farmhand-stream";
const announce = () => {
  try {
    const ch = new BroadcastChannel(STREAM_CHANNEL);
    ch.postMessage("saved");
    ch.close();
  } catch {
    // (an old browser: the Stream page catches up on its next look, within 5 seconds)
  }
};
// Open the window (or bring it forward if it's open already)
export const openYouTubeSettings = () => {
  const w = window.open(WINDOW_PATH, WINDOW_NAME, "popup,width=720,height=900");
  w?.focus();
};

export const CATEGORIES = [
  ["28", "Science & Technology"], ["27", "Education"], ["26", "Howto & Style"], ["22", "People & Blogs"], ["24", "Entertainment"], ["20", "Gaming"],
];
export const PRIVACY = [["public", "Public", "anyone can find and watch it"], ["unlisted", "Unlisted", "only people with the link"], ["private", "Private", "only you"]];
const LATENCY = [["normal", "Normal", "smoothest, ~15-30 s behind"], ["low", "Low", "~5-10 s behind"], ["ultraLow", "Ultra-low", "~2-5 s behind, no 1440p"]];
const TAGS_MAX = 500; // YouTube's own limit, all the tags together

// the tags as typed (commas between them) and as kept: [words], blanks and repeats left out
const tagsOf = (text) => [...new Set(text.split(",").map((t) => t.trim()).filter(Boolean))];
const tagsLength = (tags) => tags.join(",").length;

// The summary on the Stream page, and the button that opens the window
export function YouTubeSettingsButton({ shown, youtube, keySet, onOpen }) {
  // signed in: YouTube gives Farmhand its key (and makes each broadcast); a pasted key is only needed otherwise
  const ready = youtube.signedIn || keySet;
  const yt = shown.youtube || {};
  const privacy = PRIVACY.find(([k]) => k === yt.privacy)?.[1] || "Public";
  const parts = [
    privacy,
    shown.title ? `“${shown.title.length > 40 ? `${shown.title.slice(0, 40)}…` : shown.title}”` : "no title (YouTube's own)",
    `${(yt.tags || []).length} tag${(yt.tags || []).length === 1 ? "" : "s"}`,
    youtube.signedIn ? "key from YouTube" : keySet ? "key saved" : "no stream key",
    youtube.signedIn ? `signed in${youtube.channel ? ` as ${youtube.channel}` : ""}` : "not signed in",
  ];
  return (
    <div data-testid="stream-youtube-settings" style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
      <button type="button" data-testid="stream-youtube-settings-open" onClick={onOpen} style={headerButton()}>
        <Youtube size={14} /> YouTube settings
      </button>
      <span style={uiText(12, ready ? c.textMuted : c.amber, { flex: 1, minWidth: 200 })}>{parts.join(" · ")}</span>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, borderTop: `1px solid ${c.border}`, paddingTop: 12 }}>
      <div style={uiText(13, c.heading, { fontWeight: 600 })}>{title}</div>
      {children}
    </div>
  );
}

const field = { ...fieldBox(), padding: "6px 8px" };
const column = uiText(12, c.textMuted, { display: "flex", flexDirection: "column", gap: 4 });

// The window's page: reads the stream's settings (and again every 5 seconds, for the sign-in and the key; what's typed
// here isn't touched), and saves them.
export function YouTubeSettingsWindow() {
  const [page, setPage] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [busy, setBusy] = useState(null);
  const [problem, setProblem] = useState(null);
  const [savedAt, setSavedAt] = useState(null);

  useEffect(() => {
    document.title = "YouTube settings · Farmhand";
    let live = true;
    const look = (first) =>
      (first === true || !document.hidden) &&
      getStream().then((p) => live && (setPage(p), setLoadError(null))).catch((e) => live && setLoadError(errorText(e)));
    look(true);
    const timer = setInterval(look, 5000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);

  // the account panel's and the form's asks: the page as the server answered, or null (the reason shown)
  const ask = async (what, call) => {
    setBusy(what);
    setProblem(null);
    try {
      const p = await call();
      setPage(p);
      announce();
      return p;
    } catch (e) {
      setProblem(errorText(e));
      return null;
    } finally {
      setBusy(null);
    }
  };

  return (
    <div style={{ minHeight: "100vh", background: c.bg, padding: "20px 16px" }}>
      <main style={{ maxWidth: 680, margin: "0 auto" }}>
        <div style={uiText(20, c.heading, { fontWeight: 700, display: "flex", alignItems: "center", gap: 8, marginBottom: 14 })}>
          <Youtube size={20} /> YouTube settings
        </div>
        {!page ? (
          <div style={uiText(13, loadError ? c.danger : c.textFaint)}>{loadError ? `Couldn't reach Farmhand: ${loadError}` : "Loading…"}</div>
        ) : (
          <YouTubeSettingsForm
            shown={page.settings} keySet={page.settings.keySet} youtube={page.youtube} status={page.status} ask={ask} busy={busy}
            problem={problem} savedAt={savedAt}
            onSave={async (fields) => {
              const p = await ask("save", () => saveStream(fields));
              if (p) setSavedAt(new Date());
              return p;
            }}
            onForgetKey={() => ask("save", () => saveStream({ clearKey: true }))}
          />
        )}
      </main>
    </div>
  );
}

// The settings themselves. `shown`: the stream's settings (title, description, youtube: {...}); `onSave(fields)`:
// saves just these, the page as the server answered or null; `keySet`, `onForgetKey`; `youtube`, `status`, `ask`,
// `busy`: the account's (YouTubeAccountPanel); `problem`: what the server last refused; `savedAt`: when last saved.
function YouTubeSettingsForm({ shown, onSave, keySet, onForgetKey, youtube, status, ask, busy, problem, savedAt }) {
  const [form, setForm] = useState(() => ({
    title: shown.title || "", description: shown.description || "",
    tags: (shown.youtube?.tags || []).join(", "),
    category: shown.youtube?.category || "28", privacy: shown.youtube?.privacy || "public", madeForKids: !!shown.youtube?.madeForKids,
    latency: shown.youtube?.latency || "normal", dvr: shown.youtube?.dvr !== false, autoStart: shown.youtube?.autoStart !== false,
    autoStop: shown.youtube?.autoStop !== false,
  }));
  const [key, setKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const set = (what) => setForm((f) => ({ ...f, ...what }));
  const tags = tagsOf(form.tags);
  const save = async () => {
    setSaving(true);
    const p = await onSave({
      title: form.title, description: form.description, streamKey: key.trim(),
      youtube: { tags, category: form.category, privacy: form.privacy, madeForKids: form.madeForKids, latency: form.latency, dvr: form.dvr,
        autoStart: form.autoStart, autoStop: form.autoStop },
    });
    setSaving(false);
    if (p) setKey("");
  };

  return (
    <div style={{ background: c.panel, border: `1px solid ${c.border}`, borderRadius: 6, padding: 16 }}>
      <div data-testid="youtube-settings-window" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={help}>
          Used for each broadcast when you go live; while live, the title, description, tags and privacy change on the one
          going out straight away.
        </div>

        <Section title="The video">
          <label style={column}>
            <span>Title <span style={uiText(11, c.textFaint)}>{form.title.length}/100</span></span>
            <input data-testid="yt-title" value={form.title} maxLength={100} onChange={(e) => set({ title: e.target.value })}
              placeholder="Printing 24/7 at the 3D Printing Elves farm" style={field} />
          </label>
          <label style={column}>
            <span>Description <span style={uiText(11, c.textFaint)}>{form.description.length}/5000</span></span>
            <textarea data-testid="yt-description" value={form.description} maxLength={5000} rows={4} onChange={(e) => set({ description: e.target.value })}
              placeholder="What's printing, who it's for, and where to find you" style={{ ...field, resize: "vertical", lineHeight: 1.5 }} />
          </label>
          <label style={column}>
            <span>
              Tags <span style={uiText(11, tagsLength(tags) > TAGS_MAX ? c.danger : c.textFaint)}>{tags.length} · {tagsLength(tags)}/{TAGS_MAX} characters</span>
            </span>
            <input data-testid="yt-tags" value={form.tags} onChange={(e) => set({ tags: e.target.value })}
              placeholder="3D Printing Elves, 3D print farm, 3D printed toys, toys for kids, 24/7 live stream" style={field} />
            <span style={uiText(11, c.textFaint)}>Commas between them. 10–15 that match what's on screen do best.</span>
          </label>
          {tags.length > 0 && (
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              {tags.map((t) => (
                <span key={t} style={uiText(11, c.textPrimary, { border: `1px solid ${c.border}`, borderRadius: 10, padding: "1px 8px" })}>{t}</span>
              ))}
            </div>
          )}
          <label style={label12}>
            Category
            <select data-testid="yt-category" value={form.category} onChange={(e) => set({ category: e.target.value })} style={field}>
              {CATEGORIES.map(([k, name]) => <option key={k} value={k}>{name}</option>)}
            </select>
          </label>
        </Section>

        <Section title="Who can watch">
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            {PRIVACY.map(([k, name, what]) => (
              <label key={k} style={label12} title={what}>
                <input type="radio" name="yt-privacy" data-testid={`yt-privacy-${k}`} checked={form.privacy === k} onChange={() => set({ privacy: k })} />
                {name} <span style={uiText(11, c.textFaint)}>({what})</span>
              </label>
            ))}
          </div>
          <label style={label12}>
            <input type="checkbox" data-testid="yt-made-for-kids" checked={form.madeForKids} onChange={(e) => set({ madeForKids: e.target.checked })} />
            Made for kids <span style={uiText(11, c.textFaint)}>(YouTube then turns off chat and some features)</span>
          </label>
          <div style={help}>Over-18 only: set on the broadcast in YouTube Studio (Edit → Age restriction); YouTube doesn't let apps set it.</div>
        </Section>

        <Section title="The stream on YouTube">
          <label style={label12}>
            Latency
            <select data-testid="yt-latency" value={form.latency} onChange={(e) => set({ latency: e.target.value })} style={field}>
              {LATENCY.map(([k, name, what]) => <option key={k} value={k}>{name} ({what})</option>)}
            </select>
          </label>
          <label style={label12}>
            <input type="checkbox" checked={form.dvr} onChange={(e) => set({ dvr: e.target.checked })} />
            Viewers can rewind (DVR)
          </label>
          <label style={label12}>
            <input type="checkbox" data-testid="yt-auto-start" checked={form.autoStart} onChange={(e) => set({ autoStart: e.target.checked })} />
            Starts by itself when the stream arrives <span style={uiText(11, c.textFaint)}>(no YouTube Studio needed)</span>
          </label>
          <label style={label12}>
            <input type="checkbox" checked={form.autoStop} onChange={(e) => set({ autoStop: e.target.checked })} />
            Ends by itself when Farmhand stops
          </label>
        </Section>

        <Section title="Stream key">
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input
              data-testid="yt-stream-key" type={showKey ? "text" : "password"} autoComplete="new-password" value={key} onChange={(e) => setKey(e.target.value)}
              placeholder={keySet ? "Saved. Type a new one to replace it" : "Paste your stream key"} style={{ ...field, flex: 1, minWidth: 0 }}
            />
            <button type="button" onClick={() => setShowKey(!showKey)} aria-label={showKey ? "Hide" : "Show"} style={{ ...headerButton(), padding: "0 7px" }}>
              {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
            {keySet && (
              <button type="button" onClick={onForgetKey} disabled={!!busy} style={headerButton()}>
                Forget key
              </button>
            )}
          </div>
          <div style={help}>
            {youtube.signedIn
              ? "Signed in, Farmhand gets its own key from YouTube and makes each broadcast itself, so there's nothing to paste here."
                + " A key pasted here is used only after signing out."
              : "Sign in below and Farmhand gets its own key from YouTube. Or paste one: in YouTube Studio, Create → Go live → Stream,"
                + " then Copy next to Stream key. It stays in Farmhand: it isn't shown again."}
          </div>
        </Section>

        <div style={{ borderTop: `1px solid ${c.border}`, paddingTop: 12 }}>
          <YouTubeAccountPanel youtube={youtube} status={status} ask={ask} busy={busy} bare />
        </div>
      </div>
      <div
        style={{
          position: "sticky", bottom: 0, background: c.panel, display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 8,
          borderTop: `1px solid ${c.border}`, padding: "12px 0 0", marginTop: 12, flexWrap: "wrap",
        }}
      >
        <span style={uiText(12, problem || tagsLength(tags) > TAGS_MAX ? c.danger : c.green, { flex: 1, minWidth: 200, lineHeight: 1.5 })}>
          {tagsLength(tags) > TAGS_MAX
            ? `The tags come to ${tagsLength(tags)} characters; YouTube allows ${TAGS_MAX}.`
            : problem || (savedAt ? `Saved at ${savedAt.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}${status.live ? ", and sent to the broadcast going out" : ""}.` : "")}
        </span>
        <button type="button" onClick={() => window.close()} disabled={saving} style={cancelButton(saving)}>Close window</button>
        <button type="button" data-testid="yt-save" onClick={save} disabled={saving || tagsLength(tags) > TAGS_MAX} style={primaryButton(saving)}>
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </div>
  );
}
