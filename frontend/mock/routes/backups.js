// A Klipper printer's config backups (backend: routers/config_backups.py, services/config_backups.py): its config
// folder and Moonraker database, in the printer backups folder ("backup" in the Farmhand folder unless one is chosen in
// Settings), the newest 10 per printer. Each reachable sample
// Klipper printer starts with three; a new one is taken from the sample config, which changes a little each time.
import { HttpError, nowUnix } from "../core.js";
import { DAY, iso } from "../data.js";

const KEEP = 10;
const DATABASE_DIR = "moonraker-database";

const sampleConfig = (p, n) => ({
  "printer.cfg": `[include mainsail.cfg]\n[include macros/*.cfg]\n\n[printer]\nkinematics: corexy\nmax_velocity: ${300 + n * 20}\nmax_accel: 5000\n\n[stepper_x]\nstep_pin: PF13\nposition_max: 300\n`,
  "moonraker.conf": "[server]\nhost: 0.0.0.0\nport: 7125\n\n[authorization]\ntrusted_clients:\n  192.168.10.0/24\n",
  "mainsail.cfg": `[virtual_sdcard]\npath: ~/printer_data/gcodes\n[pause_resume]\n${n > 0 ? "[display_status]\n" : ""}`,
  "macros/print_start.cfg": `[gcode_macro PRINT_START]\ngcode:\n  G28\n  BED_MESH_CALIBRATE\n${n > 1 ? "  CLEAN_NOZZLE\n" : ""}`,
  ...(n > 0 ? { "macros/clean_nozzle.cfg": "[gcode_macro CLEAN_NOZZLE]\ngcode:\n  G1 X250 Y300 F6000\n" } : {}),
  [`${DATABASE_DIR}/history.json`]: JSON.stringify({ count: 42 + n, jobs: [], totals: { total_jobs: 42 + n } }, null, 2),
  [`${DATABASE_DIR}/mainsail.json`]: JSON.stringify({ namespace: "mainsail", value: { general: { printername: p.name }, dashboard: { columns: 2 + n } } }, null, 2),
  [`${DATABASE_DIR}/maintenance.json`]: JSON.stringify({ namespace: "maintenance", value: {} }, null, 2),
});

export function backupsRoutes(ctx) {
  const { downloadRoutes, fail404, farm, on, printer, reachMoonraker, requireConfirm, runningJob } = ctx;

  const isKlipper = (p) => !p.prusalink;
  // SSH to the printer's Pi: set up on the even-numbered sample printers (their backups hold Moonraker's database file)
  const SSH_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMockMockMockMockMockMockMockMockMockMock farmhand";
  const hasSsh = (p) => p.id % 2 === 0;
  // Its last good SSH login ({tested_at, user, host}) or null, as the real API remembers it: a Test SSH sets it; the
  // sample printers with SSH start out tested (their backups logged in to copy Moonraker's database)
  const sshTested = new Map();
  const sshOf = (p) => (sshTested.has(p.id) ? sshTested.get(p.id) : hasSsh(p) ? { tested_at: iso(Date.now() / 1000 - 3 * DAY), user: "pi", host: p.wired_ip || p.wireless_ip } : null);
  const everyDays = () => farm.config.preferences.config_backup_days ?? 30;
  const BACKUP_DEFAULT = "/data/nas/farm-nas/backup";
  const folderOf = () => farm.backupsFolder || BACKUP_DEFAULT;
  const backupsLocation = () => ({
    path: folderOf(), is_default: !farm.backupsFolder, default_path: BACKUP_DEFAULT,
    status: { exists: true, writable: true, marker_ok: true, ready: true },
  });

  const make = (p, takenAt, trigger, files) => ({
    id: (farm.nextIds.configBackup = (farm.nextIds.configBackup || 100) + 1), taken_at: iso(takenAt), trigger,
    folder: `${folderOf()}/${p.name}/${iso(takenAt).slice(0, 19).replace("T", "_").replaceAll(":", "-")}`,
    files, skipped: [{ path: "printer-20260101_120000.cfg", reason: "a backup, temporary or results file" }],
  });
  // newest first
  const backupsOf = (p) => {
    farm.configBackups ??= {};
    if (!farm.configBackups[p.id]) {
      farm.configBackups[p.id] = isKlipper(p) && p.moonraker?.reachable
        ? [2, 1, 0].map((n) => make(p, nowUnix() - (n * 30 + 3) * DAY, n === 2 ? "manual" : "automatic", sampleConfig(p, 2 - n)))
        : [];
      farm.configBackups[p.id].reverse();
    }
    return farm.configBackups[p.id];
  };
  const find = (p, id) => backupsOf(p).find((b) => b.id === Number(id)) || fail404("That backup isn't kept any more.");
  const previousOf = (p, b) => backupsOf(p)[backupsOf(p).indexOf(b) + 1] || null;
  const changes = (b, prev) => prev && {
    added: Object.keys(b.files).filter((k) => !(k in prev.files)).sort(),
    changed: Object.keys(b.files).filter((k) => k in prev.files && prev.files[k] !== b.files[k]).sort(),
    removed: Object.keys(prev.files).filter((k) => !(k in b.files)).sort(),
  };
  const size = (text) => Buffer.byteLength(text);
  const summary = (p, b) => {
    const prev = previousOf(p, b);
    return {
      id: b.id, taken_at: b.taken_at, trigger: b.trigger, folder: b.folder, file_count: Object.keys(b.files).length,
      total_bytes: Object.values(b.files).reduce((t, v) => t + size(v), 0), skipped: b.skipped, has_database: hasSsh(p), previous_id: prev?.id ?? null, changes: changes(b, prev),
    };
  };
  const list = (p) => {
    if (!isKlipper(p)) return { supported: false, keep: KEEP, every_days: everyDays(), next_due_at: null, folder: null, ssh: null, backups: [] };
    const rows = backupsOf(p);
    const days = everyDays();
    const due = days > 0 ? (rows[0] ? Date.parse(rows[0].taken_at) / 1000 + days * DAY : nowUnix()) : null;
    return { supported: true, keep: KEEP, every_days: days, next_due_at: due ? iso(due) : null, folder: folderOf(), ssh: sshOf(p), backups: rows.map((b) => summary(p, b)) };
  };
  const take = (p, trigger) => {
    if (!isKlipper(p)) throw new HttpError(422, "PrusaLink printers have no config folder Farmhand can back up.");
    reachMoonraker(p);
    const rows = backupsOf(p);
    const current = farm.liveConfig?.[p.id] || sampleConfig(p, 3);
    const b = make(p, nowUnix(), trigger, { ...current });
    rows.unshift(b);
    rows.splice(KEEP);
    return b;
  };
  const fileOf = (b, path) => (path in b.files ? b.files[path] : fail404(`${path} isn't in that backup.`));

  on("GET", "/printers/config-backups/location", () => backupsLocation());
  on("PUT", "/printers/config-backups/location", (_, body) => {
    farm.backupsFolder = body.path && body.path.trim() ? body.path.trim() : null;
    return backupsLocation();
  });
  on("PUT", "/printers/config-backups/schedule", (_, body) => {
    const d = body.every_days;
    if (!Number.isInteger(d) || d < 0 || d > 365) throw new HttpError(422, "Say how many days between automatic backups: a whole number from 1 to 365, or 0 for never.");
    farm.config.preferences.config_backup_days = d;
    return { every_days: d };
  });
  on("GET", "/printers/:id/config-backups", ({ id }) => list(printer(id)));
  on("POST", "/printers/:id/config-backups", ({ id }) => {
    const p = printer(id);
    const b = take(p, "manual");
    return [201, { id: b.id, ...list(p) }];
  });
  on("GET", "/printers/:id/config-backups/:bid", ({ id, bid }) => {
    const p = printer(id);
    const b = find(p, bid);
    const prev = previousOf(p, b);
    const files = Object.keys(b.files).sort().map((path) => ({
      path, size: size(b.files[path]), modified: nowUnix() - 5 * DAY, database: path.startsWith(`${DATABASE_DIR}/`),
      change: !prev ? null : !(path in prev.files) ? "added" : prev.files[path] !== b.files[path] ? "changed" : "same",
    }));
    return { ...summary(p, b), files };
  });
  on("GET", "/printers/:id/config-backups/:bid/file", ({ id, bid }, _b, q) => {
    const b = find(printer(id), bid);
    const text = fileOf(b, q.get("path"));
    return { path: q.get("path"), size: size(text), binary: false, text };
  });
  on("GET", "/printers/:id/config-backups/:bid/diff", ({ id, bid }, _b, q) => {
    const p = printer(id);
    const b = find(p, bid);
    const path = q.get("path");
    const now = fileOf(b, path);
    const prev = previousOf(p, b);
    const out = { path, previous_id: prev?.id ?? null, previous_taken_at: prev?.taken_at ?? null, binary: false, diff: null, change: null };
    if (!prev) return out;
    const before = prev.files[path];
    out.change = before == null ? "added" : before === now ? "same" : "changed";
    if (out.change === "same") return { ...out, diff: "" };
    // a simple line diff: enough for the mockup (the real one is difflib's unified diff)
    const a = (before ?? "").split("\n");
    const bLines = now.split("\n");
    const lines = [`--- ${path} (before)`, `+++ ${path} (this backup)`, `@@ -1,${a.length} +1,${bLines.length} @@`];
    const inA = new Set(a);
    const inB = new Set(bLines);
    for (const l of a) if (!inB.has(l)) lines.push(`-${l}`);
    for (const l of bLines) lines.push(inA.has(l) ? ` ${l}` : `+${l}`);
    return { ...out, diff: lines.join("\n") };
  });
  on("POST", "/printers/:id/config-backups/:bid/restore", ({ id, bid }, body) => {
    const p = printer(id);
    const b = find(p, bid);
    if (body.path?.startsWith(`${DATABASE_DIR}/`)) throw new HttpError(409, "What came from Moonraker's database can be downloaded, but not put back on the printer.");
    const text = fileOf(b, body.path);
    if (runningJob(p)) throw new HttpError(409, `${p.name} is printing. Put files back once the print has finished.`);
    const safety = take(p, "before_restore");
    (farm.liveConfig ??= {})[p.id] = { ...safety.files, [body.path]: text };
    return {
      path: body.path, from_backup_taken_at: b.taken_at, safety_backup_id: safety.id,
      message: `${body.path} is back on ${p.name} as it was in that backup. Restart Klipper (FIRMWARE_RESTART, or Restart in Mainsail) for it to take effect.`,
      ...list(p),
    };
  });
  // Restore: what it would change, then the whole backup back (config files and Moonraker settings; nothing deleted)
  const NOT_RESTORED = new Set(["history", "moonraker", "gcode_metadata", "update_manager", "announcements"]);
  const settingsOf = (files) => Object.fromEntries(Object.entries(files).filter(([k]) => k.startsWith(`${DATABASE_DIR}/`))
    .map(([, v]) => JSON.parse(v)).filter((d) => d.namespace && !NOT_RESTORED.has(d.namespace)).map((d) => [d.namespace, d.value]));
  const plan = (p, b) => {
    const now = farm.liveConfig?.[p.id] || sampleConfig(p, 3);
    const config = (files) => Object.keys(files).filter((k) => !k.startsWith(`${DATABASE_DIR}/`));
    const locked = config(b.files).filter((k) => k === "mainsail.cfg" && now[k] !== b.files[k]);
    const putBack = config(b.files).filter((k) => k !== "mainsail.cfg" && now[k] !== b.files[k]).sort();
    const overSsh = hasSsh(p) ? locked : [];
    const readOnly = hasSsh(p) ? [] : locked;
    const nowSettings = settingsOf(now);
    const settings = Object.entries(settingsOf(b.files)).map(([ns, value]) => ({
      namespace: ns, keys: Object.keys(value).filter((k) => JSON.stringify(nowSettings[ns]?.[k]) !== JSON.stringify(value[k])).sort(),
    })).filter((x) => x.keys.length);
    return {
      files: { put_back: putBack, over_ssh: overSsh, same: config(b.files).length - putBack.length - locked.length, read_only: readOnly },
      settings, left_alone: config(now).filter((k) => !(k in b.files)).sort(),
    };
  };
  on("GET", "/printers/:id/config-backups/:bid/restore-preview", ({ id, bid }) => {
    const p = printer(id);
    const b = find(p, bid);
    reachMoonraker(p);
    return { backup_id: b.id, taken_at: b.taken_at, ...plan(p, b) };
  });
  on("POST", "/printers/:id/config-backups/:bid/restore-all", ({ id, bid }) => {
    const p = printer(id);
    const b = find(p, bid);
    if (runningJob(p)) throw new HttpError(409, `${p.name} is printing. Put files back once the print has finished.`);
    const what = plan(p, b);
    const safety = take(p, "before_restore");
    const next = { ...safety.files };
    for (const k of [...what.files.put_back, ...what.files.over_ssh]) next[k] = b.files[k];
    for (const [k, v] of Object.entries(b.files)) if (k.startsWith(`${DATABASE_DIR}/`) && !k.endsWith("history.json")) next[k] = v;
    (farm.liveConfig ??= {})[p.id] = next;
    const settingsWritten = what.settings.reduce((n, x) => n + x.keys.length, 0);
    const parts = [what.files.put_back.length && `${what.files.put_back.length} config file${what.files.put_back.length === 1 ? "" : "s"} put back`,
      settingsWritten && `${settingsWritten} Moonraker setting${settingsWritten === 1 ? "" : "s"} put back`].filter(Boolean);
    const message = parts.length
      ? `${parts.join(" and ")} on ${p.name}, as in the backup of ${b.taken_at.slice(0, 16).replace("T", " ")} UTC.${what.files.put_back.length ? " Restart Klipper (FIRMWARE_RESTART, or Restart in Mainsail) for it to take effect." : ""}${settingsWritten ? " Reload Mainsail's page to see its settings." : ""}`
      : `Nothing to put back: ${p.name} is already as it was in that backup.`;
    return { from_backup_taken_at: b.taken_at, safety_backup_id: safety.id, restored: [...what.files.put_back, ...what.files.over_ssh], settings_written: settingsWritten, failed: [], message, ...what, ...list(p) };
  });
  on("GET", "/printers/config-backups/ssh-key", () => ({ public_key: SSH_KEY }));
  on("POST", "/printers/:id/ssh/test", ({ id }) => {
    const p = printer(id);
    const host = p.wired_ip || p.wireless_ip;
    const answer = hasSsh(p)
      ? { ok: true, user: "pi", host, error: null, kind: null, tested_at: iso(Date.now() / 1000) }
      : { ok: false, user: null, host: null, kind: "no_key", tested_at: null, error: `The printer (pi@${host}) didn't let Farmhand in: add Farmhand's SSH key to its ~/.ssh/authorized_keys (Set up SSH, in the Backups section).` };
    sshTested.set(p.id, answer.ok ? { tested_at: answer.tested_at, user: "pi", host } : null);
    return answer;
  });
  on("POST", "/printers/:id/config-backups/:bid/restore-database", ({ id, bid }) => {
    const p = printer(id);
    const b = find(p, bid);
    if (!hasSsh(p)) throw new HttpError(409, "This backup has no copy of Moonraker's database: SSH to the printer wasn't set up when it was taken.");
    if (runningJob(p)) throw new HttpError(409, `${p.name} is printing. Put files back once the print has finished.`);
    const safety = take(p, "before_restore");
    return {
      from_backup_taken_at: b.taken_at, safety_backup_id: safety.id, ...list(p),
      message: `Moonraker's database on ${p.name} is back as it was in the backup of ${b.taken_at.slice(0, 16).replace("T", " ")} UTC (print history, Mainsail's settings, maintenance). Moonraker restarts itself now; Mainsail reconnects in a few seconds.`,
    };
  });
  on("DELETE", "/printers/:id/config-backups/:bid", ({ id, bid }, _b, q) => {
    requireConfirm(q, "Deleting a backup removes its files from the NAS — pass confirm=true to proceed");
    const p = printer(id);
    const rows = backupsOf(p);
    rows.splice(rows.indexOf(find(p, bid)), 1);
    return list(p);
  });

  // downloads: stand-ins, as the mockup's other downloads are
  downloadRoutes.push(
    [/^\/printers\/(\d+)\/config-backups\/(\d+)\/download$/, (m) => [`${printer(m[1]).name}-backup-${m[2]}.zip`]],
    [/^\/printers\/(\d+)\/config-backups\/(\d+)\/file\/download$/, () => ["config-file.cfg"]],
  );
  return {};
}
