import { c } from "../theme.js";
import { panelBox, uiText } from "../styles.js";

// Connecting Farmhand to a YouTube channel, step by step: its own page (/help/youtube), opened in a new tab from the
// Stream page's YouTube account panel. Making the Google Cloud app Farmhand signs in with, then signing in from Farmhand.
// Google's console changes its names now and then: the steps say where things are today, and what they used to be called.

const link = (href, text) => (
  <a href={href} target="_blank" rel="noreferrer" style={{ color: c.amber }}>
    {text}
  </a>
);
const b = (text) => <b style={{ color: c.heading }}>{text}</b>;

function Step({ n, title, children }) {
  return (
    <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
      <div style={{ flexShrink: 0, width: 28, height: 28, borderRadius: 14, background: c.amberDim, border: `1px solid ${c.amberBorder}`, display: "flex", alignItems: "center", justifyContent: "center", ...uiText(13, c.heading, { fontWeight: 700 }) }}>
        {n}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={uiText(15, c.heading, { fontWeight: 600, marginBottom: 6 })}>{title}</div>
        <div style={uiText(14, c.textPrimary, { lineHeight: 1.65 })}>{children}</div>
      </div>
    </div>
  );
}

const Part = ({ title, note, children }) => (
  <section style={panelBox({ padding: 20, display: "flex", flexDirection: "column", gap: 18 })}>
    <div>
      <div style={uiText(17, c.heading, { fontWeight: 700 })}>{title}</div>
      {note && <div style={uiText(13, c.textMuted, { marginTop: 4, lineHeight: 1.5 })}>{note}</div>}
    </div>
    {children}
  </section>
);
const list = { margin: "6px 0 0", paddingLeft: 20, display: "flex", flexDirection: "column", gap: 4 };

export function YouTubeGuide() {
  return (
    <div style={{ minHeight: "100vh", background: c.bg, padding: "32px 16px" }}>
      <main data-testid="youtube-guide" style={{ maxWidth: 760, margin: "0 auto", display: "flex", flexDirection: "column", gap: 18 }}>
        <header>
          <div style={uiText(24, c.heading, { fontWeight: 700 })}>Connect Farmhand to your YouTube channel</div>
          <div style={uiText(14, c.textMuted, { marginTop: 8, lineHeight: 1.6 })}>
            Streaming only needs the stream key. Signing Farmhand in to YouTube lets it set your live broadcast's{" "}
            {b("title and description")} for you. You make a small app in Google Cloud for Farmhand to sign in with, paste its two
            codes into Farmhand, and sign in with a code. About 10 minutes, once. Use the Google account that owns the YouTube channel
            all the way through.
          </div>
        </header>

        <Part title="Part 1: Google Cloud" note="In your browser, signed in to the Google account that owns the channel.">
          <Step n={1} title="Make a project">
            Open {link("https://console.cloud.google.com/projectcreate", "Google Cloud: New project")}, name it {b("Farmhand")} and press{" "}
            {b("Create")}. Make sure it's the project chosen at the top of the page for the rest of these steps.
          </Step>
          <Step n={2} title="Turn on the YouTube API">
            Open {link("https://console.cloud.google.com/apis/library/youtube.googleapis.com", "YouTube Data API v3")} (or{" "}
            {b("APIs & Services → Library")} and search for it) and press {b("Enable")}.
          </Step>
          <Step n={3} title="Set up Google Auth Platform">
            Open {link("https://console.cloud.google.com/auth/overview", "Google Auth Platform")} (search for it at the top; it used to be
            called the {b("OAuth consent screen")}) and press {b("Get started")}:
            <ul style={list}>
              <li>{b("App information")}: app name {b("Farmhand")}, and your email as the user support email.</li>
              <li>{b("Audience")}: {b("External")}.</li>
              <li>{b("Contact information")}: your email.</li>
              <li>{b("Finish")}: agree to Google's policy, then {b("Create")}.</li>
            </ul>
          </Step>
          <Step n={4} title="Add yourself as a test user">
            In the menu on the left, open {link("https://console.cloud.google.com/auth/audience", "Audience")}. Leave the status as{" "}
            {b("Testing")}. Under {b("Test users")}, press {b("Add users")}, add the Google account that owns the channel, and save.
            <div style={uiText(13, c.textMuted, { marginTop: 6, lineHeight: 1.6 })}>
              In Testing, Google ends Farmhand's sign-in after 7 days; you sign in again from Farmhand (see the end of this page for
              staying signed in for good).
            </div>
          </Step>
          <Step n={5} title="Make the client Farmhand signs in with">
            In the menu on the left, open {link("https://console.cloud.google.com/auth/clients", "Clients")} and press{" "}
            {b("Create client")}. For {b("Application type")} choose {b("TVs and Limited Input devices")} (the kind that signs in with
            a code), name it {b("Farmhand")} and press {b("Create")}. Google shows a {b("Client ID")} (ending in{" "}
            <code>.apps.googleusercontent.com</code>) and a {b("Client secret")}: keep that window open, or download them.
          </Step>
        </Part>

        <Part title="Part 2: Farmhand" note="On the Stream page, in the YouTube account panel.">
          <Step n={6} title="Paste the client">
            Paste the {b("Client ID")} and {b("Client secret")} into their boxes and press {b("Save client")}. Both are hidden as dots
            (the eye shows them); the secret stays on the Farmhand server and never comes back to the page.
          </Step>
          <Step n={7} title="Sign in">
            Press {b("Sign in to YouTube")}. Farmhand shows a short code and {b("google.com/device")}. On any computer or phone, open{" "}
            {link("https://www.google.com/device", "google.com/device")}, type the code, and choose the Google account that owns the
            channel.
          </Step>
          <Step n={8} title="Get past Google's warning">
            Google says {b("“Google hasn't verified this app”")}: it's your own app, so that's expected. Press {b("Continue")} (or{" "}
            {b("Advanced → Go to Farmhand (unsafe)")}), then allow Farmhand to manage your YouTube account: setting the broadcast's
            title and description needs that.
          </Step>
          <Step n={9} title="Done">
            Within a few seconds the panel says {b("Signed in")}, with the channel's name. Write a title and description in{" "}
            {b("YouTube title and description")}, Save, and go live: Farmhand sets them on the broadcast once YouTube has started it
            (usually within a minute).
          </Step>
        </Part>

        <Part title="If something goes wrong">
          <ul style={{ ...list, margin: 0, gap: 10, ...uiText(14, c.textPrimary, { lineHeight: 1.6 }) }}>
            <li>{b("“Access blocked” or “invalid client”")}: the client wasn't made as {b("TVs and Limited Input devices")}. Make a new one of that kind (step 5) and paste it in with {b("Change")}.</li>
            <li>{b("“Access denied” or “not a test user”")}: the account you signed in with isn't in {b("Test users")} (step 4). Add it, or sign in with the one that is.</li>
            <li>{b("Signed out after a week")}: that's Testing (step 4). Press {b("Sign in to YouTube")} again; the stream itself keeps going either way.</li>
            <li>{b("The title isn't set")}: the YouTube account panel and {b("YouTube title and description")} say why. Most often the stream hasn't reached YouTube yet; Farmhand keeps trying for about 4 minutes after going live.</li>
          </ul>
        </Part>

        <Part title="Staying signed in for good (optional)" note="Needs a website of your own.">
          <div style={uiText(14, c.textPrimary, { lineHeight: 1.65 })}>
            To keep Farmhand signed in without the weekly sign-in, the app has to be {b("In production")} instead of Testing. Google
            then wants these on {link("https://console.cloud.google.com/auth/branding", "Branding")}: an {b("App home page")} (your
            website), an {b("App privacy policy link")} (a page on the same site; it can just say Farmhand only uses the account to set
            your own stream's title and description) and the site's domain under {b("Authorized domains")} (like{" "}
            <code>example.org</code>). Save, then on {b("Audience")} press {b("Publish app")}. If Google offers verification, skip
            it: you'll still see the “unverified app” warning when signing in, and that's fine. Nothing changes in Farmhand; sign in
            once more afterwards.
          </div>
        </Part>
      </main>
    </div>
  );
}
