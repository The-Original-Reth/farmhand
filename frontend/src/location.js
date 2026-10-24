// Reads ONE pasted NAS location into protocol / server / share, so nobody has to split it up.
//
// This mirrors parse_location() in the backend and exists only to give a live "here's how I
// read that" preview and to decide which fields apply (logins are SMB-only). The server does
// its own parsing and validation and is the authority — if the two ever disagree, the server wins.
//
// Accepted:  //192.168.1.50/farmhand/Projects     \\nas\farmhand\Projects     smb://nas/farmhand
//            192.168.1.50:/volume1/farmhand       nfs://nas/volume1/farmhand   nas/farmhand (assumed SMB)

export function parseLocation(text) {
  const raw = (text || "").trim().replace(/\\/g, "/");
  if (!raw) return { error: "empty" };

  let protocol;
  let rest;
  const m = raw.match(/^([A-Za-z][A-Za-z0-9+.-]*):\/\/(.*)$/);
  if (m) {
    const scheme = m[1].toLowerCase();
    if (scheme === "smb" || scheme === "cifs") {
      protocol = "smb";
      rest = m[2];
    } else if (scheme === "nfs") {
      protocol = "nfs";
      rest = m[2];
    } else {
      return { error: "scheme" };
    }
  } else if (raw.startsWith("//")) {
    protocol = "smb";
    rest = raw.slice(2);
  } else if (/^[^/]*:/.test(raw)) {
    protocol = "nfs"; // "host:/path" — a colon before any slash
    rest = raw;
  } else {
    protocol = "smb";
    rest = raw;
  }

  rest = rest.replace(/^\/+/, "");
  const i = rest.indexOf("/");
  const head = i === -1 ? rest : rest.slice(0, i);
  const tail = i === -1 ? "" : rest.slice(i + 1);
  const trim = (x) => x.replace(/^\/+|\/+$/g, "");

  if (protocol === "nfs") {
    const server = head.endsWith(":") ? head.slice(0, -1) : head;
    const path = trim(tail);
    if (server.includes("@")) return { error: "login" };
    if (!server || !path) return { error: "path" };
    return { protocol, server, share: "/" + path };
  }

  const share = trim(tail);
  if (head.includes("@")) return { error: "login" };
  if (!head || !share) return { error: "share" };
  return { protocol, server: head, share };
}

const MESSAGES = {
  scheme: "That doesn't look like a NAS address — use //server/share (SMB) or server:/export (NFS).",
  login: "Leave the username and password out of the address — they go in the fields below.",
  path: "Add the export path after the address, like 192.168.1.50:/volume1/farmhand.",
  share: "Add the share name after the address, like //192.168.1.50/farmhand.",
};

// One line saying how an address was understood, or what's wrong with it. null while it's empty.
export function describeLocation(parsed) {
  if (parsed.error === "empty") return null;
  if (parsed.error) return { ok: false, text: MESSAGES[parsed.error] };
  if (parsed.protocol === "nfs") {
    return { ok: true, text: `NFS export ${parsed.share} on ${parsed.server}` };
  }
  const [share, ...sub] = parsed.share.split("/");
  return {
    ok: true,
    text: `SMB share “${share}” on ${parsed.server}${sub.length ? `, folder ${sub.join("/")}` : ""}`,
  };
}
