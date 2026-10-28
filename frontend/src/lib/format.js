// Numbers and times as the pages show them. A missing value reads "—".

// print time: "3h 05m", or "42m" under an hour
export const fmtDuration = (s) => {
  if (!s) return "0m";
  const minutes = Math.round(s / 60); // rounded first, so 2h 59m 50s reads 3h 00m, not 2h 60m
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h ? `${h.toLocaleString()}h ${String(m).padStart(2, "0")}m` : `${m}m`;
};
export const fmtMetres = (mm) => `${((mm || 0) / 1000).toLocaleString(undefined, { maximumFractionDigits: (mm || 0) >= 100000 ? 0 : 1 })} m`;
export const fmtWhen = (iso) => (iso ? new Date(iso).toLocaleString() : "—");
export const fmtUnix = (s) => (s ? new Date(s * 1000).toLocaleString() : "—");
// ---- energy: per print (from the history) and the whole printer (from the power meter's readings) ----
// always to the watt-hour (3 decimals), so the figures are exact rather than rounded
export const fmtKwh = (v) => (v == null ? "—" : `${v.toLocaleString(undefined, { minimumFractionDigits: 3, maximumFractionDigits: 3 })} kWh`);
// a file or a disk's size: "512 B", "3.4 MB", "120 GB"
export function formatBytes(n) {
  if (n == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v >= 10 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}
