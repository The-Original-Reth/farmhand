// Printers: listed, added, edited and deleted; their printer profiles and each profile's parts.
import { HttpError, nowUnix } from "../core.js";
import { DEFAULT_PARTS, defaultParts, iso } from "../data.js";

export function printersRoutes(ctx) {
  const { bundleOut, farm, on, printer, printerOut, requireConfirm, saveNotes } = ctx;

  on("GET", "/printers", () => [...farm.printers].sort((a, b) => a.name.localeCompare(b.name)).map(printerOut));
  // The range a scan starts with: as the real API in Docker, the /24 most of the farm's printers are on
  on("GET", "/printers/discover/range", () => {
    const count = {};
    for (const ip of farm.printers.flatMap((p) => [p.wired_ip, p.wireless_ip])) {
      const m = /^(10|172|192)\.(\d+)\.(\d+)\.\d+$/.exec(ip || "");
      if (m) count[`${m[1]}.${m[2]}.${m[3]}.0/24`] = (count[`${m[1]}.${m[2]}.${m[3]}.0/24`] || 0) + 1;
    }
    return { cidr: Object.keys(count).sort((a, b) => count[b] - count[a])[0] || null };
  });
  // A network scan (before /printers/:id, which would take "discover" for an id): a few made-up printers at fixed
  // places in the range, skipping addresses the farm's printers have. Two share MainsailOS's default hostname; the
  // Trident is on both cable and Wi-Fi, so it's listed once, at its wired IP.
  on("GET", "/printers/discover", async (_, __, q) => {
    const cidr = (q.get("cidr") || "").trim();
    const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?:\/(\d{1,2}))?$/.exec(cidr);
    if (cidr.includes(":")) throw new HttpError(422, "Only IPv4 ranges can be scanned, like 192.168.1.0/24.");
    if (!m || m.slice(1, 5).some((o) => Number(o) > 255) || Number(m[5] ?? 32) > 32) throw new HttpError(422, `'${cidr}' isn't a network range. Write it like 192.168.1.0/24.`);
    const bits = Number(m[5] ?? 32);
    const [a, b] = m.slice(1, 3).map(Number); // the farm's own network only, as the real API (is_private)
    const own = a === 10 || a === 127 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 169 && b === 254);
    if (!own || bits < 8) throw new HttpError(422, "Only your own network can be scanned: a range starting 10., 172.16 to 172.31, or 192.168.");
    if (2 ** (32 - bits) > 1024) throw new HttpError(422, `That range has ${2 ** (32 - bits)} addresses. Scan 1024 or fewer at a time (a /22 or smaller).`);
    await new Promise((done) => setTimeout(done, 2000)); // a real scan of a /24 takes a few seconds
    const start = (m.slice(1, 5).reduce((n, o) => n * 256 + Number(o), 0) >>> (32 - bits)) * 2 ** (32 - bits);
    const ipAt = (n) => [24, 16, 8, 0].map((s) => (n >>> s) & 255).join(".");
    // active printers' addresses are skipped; one found at a decommissioned printer's is listed with that printer
    const known = new Set(farm.printers.filter((p) => !p.decommissioned).flatMap((p) => [p.wired_ip, p.wireless_ip]).filter(Boolean));
    const retired = new Map(farm.printers.filter((p) => p.decommissioned).flatMap((p) => [p.wired_ip, p.wireless_ip].filter(Boolean).map((h) => [h, p])));
    const was = (f) => [f.ip, f.wired_ip, f.wireless_ip].map((h) => h && retired.get(h)).find(Boolean);
    const sample = [ // [offset, hostname, firmware, needs a key, link, the other link's offset]
      [31, "mainsailos", "Klipper", false, "wired", null],
      [32, "mainsailos", "Klipper", false, "wireless", null],
      [40, "trident-300", "Kalico", false, "wired", 41],
      [77, null, null, true, null, null],
      [129, null, "Prusa", true, null, null], // a Core One: PrusaLink wants its password, so it gives no name
    ];
    const inRange = (offset) => offset < 2 ** (32 - bits) - (bits < 31 ? 1 : 0);
    return sample
      .filter(([offset]) => inRange(offset))
      .map(([offset, hostname, firmware, needsKey, link, other]) => {
        const ip = ipAt(start + offset);
        const otherIp = other != null && inRange(other) ? ipAt(start + other) : null;
        if (firmware === "Prusa") {
          return {
            ip, connection_type: "prusalink", address: `http://${ip}`, web_url: `http://${ip}/`, hostname, firmware,
            version: null, state: null, needs_api_key: needsKey, link: null, wired_ip: null, wireless_ip: null,
          };
        }
        return {
          ip, connection_type: "moonraker", address: `http://${ip}:7125`, web_url: `http://${ip}/`, hostname, firmware,
          version: needsKey ? null : "v0.9.3", state: needsKey ? null : "ready", needs_api_key: needsKey, link,
          wired_ip: link === "wired" ? ip : null, wireless_ip: link === "wireless" ? ip : otherIp,
        };
      })
      .filter((f) => ![f.ip, f.wired_ip, f.wireless_ip].some((h) => h && known.has(h)))
      .map((f) => ({ ...f, decommissioned_id: was(f)?.id ?? null, decommissioned_name: was(f)?.name ?? null }));
  });
  on("GET", "/printers/:id", ({ id }) => printerOut(printer(id)));
  on("POST", "/printers", (_, body) => {
    if (!body.name?.trim()) throw new HttpError(422, "A printer needs a name");
    if (farm.printers.some((p) => p.name === body.name.trim())) throw new HttpError(409, `A printer named '${body.name}' already exists — name is the unique key, not IP`);
    const p = { id: farm.nextIds.printer++, name: body.name.trim(), kind: body.kind, wired_ip: body.wired_ip, wireless_ip: body.wireless_ip, decommissioned: false, created_at: iso(nowUnix()), moonraker: null, notes: "", serviceHoursSince: null, serviceHistory: [] };
    if (body.connection_type === "prusalink") {
      p.prusalink = { reachable: true, firmware: "6.2.0", username: body.prusalink_username || "maker", hasPassword: !!body.prusalink_password, password: body.prusalink_password || null, url: body.prusalink_url || null };
    } else {
      p.moonraker_url_override = body.moonraker_url || null;
      p.apiKey = body.moonraker_api_key || null;
    }
    p.cameraAddress = body.camera_address || null;
    farm.printers.push(p);
    return [201, printerOut(p)];
  });
  // As the real API: only a decommissioned printer, and only once no 3MF files are kept for it
  on("DELETE", "/printers/:id", ({ id }, _b, q) => {
    requireConfirm(q);
    const p = printer(id);
    if (!p.decommissioned) throw new HttpError(409, `${p.name} is still in use. Decommission it first (Edit), then it can be deleted.`);
    const n = farm.bundles.filter((b) => b.printer_id === p.id).length;
    if (n) throw new HttpError(409, `${p.name} still has ${n} 3MF file${n !== 1 ? "s" : ""}. Delete ${n !== 1 ? "them" : "it"} from its page first, then the printer can be deleted.`);
    farm.printers = farm.printers.filter((x) => x !== p);
    return [204, null];
  });
  on("PATCH", "/printers/:id", ({ id }, body) => {
    const p = printer(id);
    for (const k of ["name", "kind", "wired_ip", "wireless_ip", "decommissioned"]) if (k in body && body[k] !== undefined) p[k] = body[k];
    if ("moonraker_url" in body) p.moonraker_url_override = body.moonraker_url || null;
    if ("camera_address" in body) p.cameraAddress = body.camera_address || null;
    if (body.moonraker_api_key != null) p.apiKey = body.moonraker_api_key || null;
    if (body.connection_type === "moonraker") delete p.prusalink;
    if (body.connection_type === "prusalink" && !p.prusalink) p.prusalink = { reachable: true, firmware: "6.2.0", username: "maker", hasPassword: false, url: null };
    if (p.prusalink) {
      if ("prusalink_url" in body) p.prusalink.url = body.prusalink_url || null;
      if (body.prusalink_username != null) p.prusalink.username = body.prusalink_username.trim() || "maker";
      if (body.prusalink_password != null) {
        p.prusalink.hasPassword = !!body.prusalink_password;
        p.prusalink.password = body.prusalink_password || null;
      }
    }
    return printerOut(p);
  });
  on("PUT", "/printers/:id/notes", ({ id }, body) => {
    const p = printer(id);
    saveNotes(p, body, { text: "notes", rev: "notesRevision", at: "notesUpdatedAt" });
    return printerOut(p);
  });
  // Printer profiles (a printer's presets in the slicer): added, renamed and removed by hand, with the real API's rules
  const subPrinterName = (body) => {
    const name = String(body.name ?? "").trim();
    if (!name) throw new HttpError(422, "A printer profile needs a name");
    if (name.length > 120) throw new HttpError(422, "A printer profile's name can be at most 120 characters");
    return name;
  };
  const subPrinterOf = (p, subId) => {
    const s = farm.subPrinters.find((x) => x.id === Number(subId) && x.printer_id === p.id);
    if (!s) throw new HttpError(404, `No printer profile with id ${subId} on this printer`);
    return s;
  };
  const newSubPrinter = (p, name) => {
    const s = { id: farm.nextIds.subPrinter++, printer_id: p.id, name, aliases: [], parts: defaultParts(() => farm.nextIds.part++) };
    farm.subPrinters.push(s);
    return s;
  };
  // from now on a 3MF with this preset goes to s (and no longer to another of the printer's that had it)
  const remember = (s, preset) => {
    if (!preset || preset === s.name || (s.aliases || []).includes(preset)) return;
    for (const o of farm.subPrinters) if (o.printer_id === s.printer_id) o.aliases = (o.aliases || []).filter((a) => a !== preset);
    s.aliases = [...(s.aliases || []), preset];
  };
  // the printer profile a preset goes to: one known by that name, else the one called that
  const knownAs = (p, preset) =>
    farm.subPrinters.find((s) => s.printer_id === p.id && (s.aliases || []).includes(preset)) ||
    farm.subPrinters.find((s) => s.printer_id === p.id && s.name === preset);
  // which printer profile a new 3MF version goes to: picked on upload, else the one its preset goes to (as the real API)
  const subPrinterFor = (p, preset, fields = {}) => {
    let s = null;
    if (fields.sub_printer_id) {
      s = farm.subPrinters.find((x) => x.id === Number(fields.sub_printer_id) && x.printer_id === p.id);
      if (!s) throw new HttpError(422, `That printer profile isn't one of ${p.name}'s`);
    } else if (fields.new_sub_printer_name?.trim()) {
      const name = fields.new_sub_printer_name.trim().slice(0, 120);
      s = farm.subPrinters.find((x) => x.printer_id === p.id && x.name === name) || newSubPrinter(p, name);
    } else if (preset) {
      s = knownAs(p, preset) || newSubPrinter(p, preset);
    }
    if (s && preset) remember(s, preset);
    return s;
  };
  const nameTaken = (p, name, except) => {
    if (farm.subPrinters.some((s) => s.printer_id === p.id && s.name === name && s !== except)) {
      throw new HttpError(409, `${p.name} already has a printer profile named '${name}'`);
    }
  };
  on("POST", "/printers/:id/sub-printers", ({ id }, body) => {
    const p = printer(id);
    const name = subPrinterName(body);
    nameTaken(p, name);
    newSubPrinter(p, name);
    return [201, printerOut(p)];
  });
  // A copy with its parts, named as given or "<name> - copy" (- copy 2... when taken); its 3MFs and the default stay
  on("POST", "/printers/:id/sub-printers/:subId/copy", ({ id, subId }, body) => {
    const p = printer(id);
    const s = subPrinterOf(p, subId);
    let name = body?.name != null ? subPrinterName(body) : null;
    for (let n = 1; name == null; n++) {
      const tail = n === 1 ? " - copy" : ` - copy ${n}`;
      const candidate = s.name.slice(0, 120 - tail.length).trimEnd() + tail;
      if (!farm.subPrinters.some((x) => x.printer_id === p.id && x.name === candidate)) name = candidate;
    }
    nameTaken(p, name);
    const copy = newSubPrinter(p, name);
    copy.parts = s.parts.map((part) => ({ ...part, id: farm.nextIds.part++ }));
    // its printer settings, as the original's newest 3MF has them (or the ones it was copied with itself)
    const newest = farm.bundles.flatMap((b) => b.versions.map((v) => ({ b, v })))
      .filter(({ v }) => v.sub_printer_id === s.id)
      .sort((x, y) => Date.parse(y.v.uploaded_at) - Date.parse(x.v.uploaded_at))[0];
    if (newest) {
      copy.settings_copy = {
        copied_from: s.name, from_file: `${newest.v.filename || newest.b.name} · v${newest.v.version}`,
        copied_at: new Date().toISOString(), settings: { ...(farm.versionSettings[newest.v.id] || {}) },
      };
    } else if (s.settings_copy) {
      copy.settings_copy = { ...s.settings_copy, copied_from: s.name, copied_at: new Date().toISOString() };
    }
    return [201, printerOut(p)];
  });
  on("GET", "/printers/:id/sub-printers/:subId/settings-copy", ({ id, subId }) => {
    const s = subPrinterOf(printer(id), subId);
    if (!s.settings_copy) throw new HttpError(404, "This printer profile has no copied printer settings");
    return s.settings_copy;
  });
  on("PATCH", "/printers/:id/sub-printers/:subId", ({ id, subId }, body) => {
    const p = printer(id);
    const s = subPrinterOf(p, subId);
    const name = subPrinterName(body);
    nameTaken(p, name, s);
    const old = s.name;
    s.name = name;
    s.aliases = (s.aliases || []).filter((a) => a !== name); // its name now, not a name it was known by
    remember(s, old);
    return printerOut(p);
  });
  on("DELETE", "/printers/:id/sub-printers/:subId", ({ id, subId }, _b, q) => {
    requireConfirm(q);
    const p = printer(id);
    const s = subPrinterOf(p, subId);
    for (const b of farm.bundles) for (const v of b.versions) if (v.sub_printer_id === s.id) v.sub_printer_id = null;
    farm.subPrinters = farm.subPrinters.filter((x) => x !== s);
    if (p.defaultSubPrinterId === s.id) p.defaultSubPrinterId = null; // no default any more
    return printerOut(p);
  });
  on("PUT", "/printers/:id/default-sub-printer", ({ id }, body) => {
    const p = printer(id);
    p.defaultSubPrinterId = body.sub_printer_id == null ? null : subPrinterOf(p, body.sub_printer_id).id;
    return printerOut(p);
  });
  // A printer profile's parts (its Printer parts page), with the real API's checks; each change answers the whole list
  const partFields = (body) => {
    const part = String(body.part ?? "").trim();
    if (!part) throw new HttpError(422, "Say what the part is (e.g. Hotend)");
    const text = (v) => String(v ?? "").trim() || null;
    if (body.installed_on != null && !/^\d{4}-\d{2}-\d{2}$/.test(body.installed_on)) throw new HttpError(422, "The installed date isn't a date");
    return { part: part.slice(0, 120), make: text(body.make), model: text(body.model), installed_on: body.installed_on || null, note: text(body.note), in_name: body.in_name === true };
  };
  // a default part (Toolhead, Hotend...) keeps its name
  const keepDefaultName = (part, fields) => {
    if (DEFAULT_PARTS.some(([name]) => name === part.part) && fields.part !== part.part) {
      throw new HttpError(422, `${part.part} is one of the default parts, so its name can't be changed`);
    }
  };
  const partOf = (s, partId) => {
    const found = s.parts.find((x) => x.id === Number(partId));
    if (!found) throw new HttpError(404, `No part with id ${partId} on this printer profile`);
    return found;
  };
  on("GET", "/printers/:id/sub-printers/:subId/parts", ({ id, subId }) => subPrinterOf(printer(id), subId).parts);
  on("POST", "/printers/:id/sub-printers/:subId/parts", ({ id, subId }, body) => {
    const s = subPrinterOf(printer(id), subId);
    s.parts.push({ id: farm.nextIds.part++, ...partFields(body) });
    return [201, s.parts];
  });
  // The whole list at once (the page's Save): with an id it's changed, without it's added, left out it's removed
  // (confirm=true). All of it or nothing.
  on("PUT", "/printers/:id/sub-printers/:subId/parts", ({ id, subId }, body, q) => {
    const s = subPrinterOf(printer(id), subId);
    const rows = Array.isArray(body) ? body : [];
    const kept = new Set(rows.map((r) => r.id).filter((x) => x != null));
    if (s.parts.some((x) => !kept.has(x.id)) && q.get("confirm") !== "true") throw new HttpError(409, "Saving removes parts: say confirm=true");
    if (kept.size !== rows.filter((r) => r.id != null).length) throw new HttpError(422, "The same part is in the list twice");
    const checked = rows.map((r) => {
      const fields = partFields(r);
      if (r.id == null) return { fields };
      const part = partOf(s, r.id);
      keepDefaultName(part, fields);
      return { part, fields };
    });
    const changed = checked.filter((r) => r.part).map((r) => Object.assign(r.part, r.fields));
    s.parts = [...changed.sort((a, b) => a.id - b.id), ...checked.filter((r) => !r.part).map((r) => ({ id: farm.nextIds.part++, ...r.fields }))];
    return s.parts;
  });
  on("PUT", "/printers/:id/sub-printers/:subId/parts/:partId", ({ id, subId, partId }, body) => {
    const s = subPrinterOf(printer(id), subId);
    const part = partOf(s, partId);
    const fields = partFields(body);
    keepDefaultName(part, fields);
    Object.assign(part, fields);
    return s.parts;
  });
  on("DELETE", "/printers/:id/sub-printers/:subId/parts/:partId", ({ id, subId, partId }, _b, q) => {
    requireConfirm(q);
    const s = subPrinterOf(printer(id), subId);
    const gone = partOf(s, partId);
    s.parts = s.parts.filter((x) => x !== gone);
    return s.parts;
  });
  on("GET", "/printers/:id/bundles", ({ id }) => farm.bundles.filter((b) => b.printer_id === Number(id)).map(bundleOut));
  return { subPrinterName, subPrinterOf, newSubPrinter, remember, knownAs, subPrinterFor, nameTaken, partFields, keepDefaultName, partOf };
}
