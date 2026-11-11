// Signing the Stream page in to YouTube. The Google client secret is kept only as "one is saved"; signing in shows a
// made-up code and counts as done a few seconds later. Uses the stream's state and page (routes/stream.js).
import { HttpError } from "../core.js";

const CLIENT_ID_SHAPE = /^[A-Za-z0-9\-_.]{3,200}\.apps\.googleusercontent\.com$/;
const SIGN_IN_TAKES_MS = 6000;

export function youtubeRoutes(ctx) {
  const { on, streamState: state, streamPage: page, titleOutcome } = ctx;

  on("PUT", "/stream/youtube", (_, body) => {
    const y = state().youtube;
    const id = String(body.client_id || "").trim();
    if (!CLIENT_ID_SHAPE.test(id)) throw new HttpError(422, "That doesn't look like a Google client ID: it ends in .apps.googleusercontent.com.");
    if (!String(body.client_secret || "").trim() && y.client_id !== id) throw new HttpError(422, "Paste the client secret too (from the same OAuth client in Google Cloud).");
    if (y.client_id !== id) Object.assign(y, { signed_in: false, channel: null, signing_in: null });
    y.client_id = id;
    y.error = null;
    return page();
  });
  on("POST", "/stream/youtube/sign-in", () => {
    const y = state().youtube;
    if (!y.client_id) throw new HttpError(422, "Add the Google OAuth client ID and secret first.");
    y.signing_in = { user_code: "MOCK-CODE", done_at: Date.now() + SIGN_IN_TAKES_MS };
    y.error = null;
    return page();
  });
  on("POST", "/stream/youtube/sign-out", (_, body) => {
    const y = state().youtube;
    Object.assign(y, { signed_in: false, channel: null, signing_in: null, error: null });
    if (body.forget_client) y.client_id = null;
    return page();
  });
  on("POST", "/stream/youtube/apply", () => {
    const s = state();
    if (!s.youtube.signed_in) throw new HttpError(422, "Sign in to YouTube first.");
    if (!(s.title || s.description)) throw new HttpError(422, "Write a title or description first, and save it.");
    if (s.live) s.title_status = titleOutcome();
    return page();
  });
  return {};
}
