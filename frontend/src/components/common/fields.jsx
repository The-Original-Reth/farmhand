import { useRef, useState } from "react";
import { Search, Upload, X } from "lucide-react";
import { c, fs, ui } from "../../theme.js";
import { fieldBox, monoText, uiText } from "../../styles.js";
import { formatBytes } from "../../lib/format.js";
import { TrashButton } from "./ui.jsx";

// A search box with a magnifier and a clear button. Esc clears it, or leaves it when it's already empty.
// inputRef: for focusing it from outside (optional). style: the box's place on the page (width, margins).
export function SearchBox({ value, onChange, placeholder, label, testId, clearTestId, inputRef, style }) {
  const ownRef = useRef(null);
  const ref = inputRef || ownRef;
  return (
    <div style={{ position: "relative", ...style }}>
      <Search size={15} color={c.textFaint} style={{ position: "absolute", left: 11, top: 10, pointerEvents: "none" }} />
      <input
        ref={ref}
        data-testid={testId}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            if (value) onChange("");
            else e.currentTarget.blur();
          }
        }}
        placeholder={placeholder}
        aria-label={label}
        autoComplete="off"
        spellCheck={false}
        style={{ ...fieldBox(), width: "100%", boxSizing: "border-box", padding: "8px 34px 8px 34px" }}
      />
      {value && (
        <button
          data-testid={clearTestId}
          onClick={() => {
            onChange("");
            ref.current?.focus();
          }}
          aria-label="Clear search"
          title="Clear search (Esc)"
          style={{ position: "absolute", right: 6, top: 6, width: 24, height: 24, display: "flex", alignItems: "center", justifyContent: "center", background: "none", border: "none", color: c.textMuted, cursor: "pointer", padding: 0 }}
        >
          <X size={14} />
        </button>
      )}
    </div>
  );
}

// Where a file picked or dropped with a folder was in it ("Shark/Fins/Fin.stl"), or just its name
export const folderPathOf = (f) => f.folderPath || f.webkitRelativePath || f.name;

// Every file in what was dropped, folders read all the way down, each with its folderPath ("Shark/Fins/Fin.stl")
async function droppedFiles(entries) {
  const fileOf = (entry) =>
    new Promise((resolve) =>
      entry.file(
        (f) => {
          f.folderPath = entry.fullPath.replace(/^\/+/, "");
          resolve([f]);
        },
        () => resolve([])
      )
    );
  const inside = async (dir) => {
    const reader = dir.createReader();
    const all = [];
    for (;;) {
      // a folder is read a batch at a time, until an empty one
      const batch = await new Promise((resolve) => reader.readEntries(resolve, () => resolve([])));
      if (!batch.length) return all;
      all.push(...batch);
    }
  };
  const out = [];
  for (const entry of entries) {
    if (entry.isFile) out.push(...(await fileOf(entry)));
    else if (entry.isDirectory) out.push(...(await droppedFiles(await inside(entry))));
  }
  return out;
}

// `multiple`: several files can be picked or dropped at once, and `file` / `onFile` are a list of them instead. Each
// pick or drop adds to the list (the same file twice is taken once), shown under the box, each with a trash can to
// take it off again.
// `folders` (with `multiple`): a folder can be dropped or chosen too, and every file in it and the folders inside it is
// taken, each knowing where it was (folderPathOf).
export function Dropzone({ label, compact = false, onFile, file, accept, multiple = false, folders = false }) {
  const inputRef = useRef(null);
  const folderRef = useRef(null);
  const [isDragging, setIsDragging] = useState(false);

  // Matching against `accept` ourselves: browsers don't enforce the
  // input's accept attribute on a programmatic drop, only on the native
  // file picker, so a dropped file needs the same check applied by hand.
  const accepts = (filename) => {
    if (!accept) return true;
    const exts = accept.split(",").map((s) => s.trim().toLowerCase());
    const name = filename.toLowerCase();
    return exts.some((ext) => name.endsWith(ext));
  };

  // with `multiple`: these join the ones already picked
  const add = (more) => {
    if (!more.length) return;
    const have = file || [];
    const key = (f) => `${folderPathOf(f)}|${f.size}|${f.lastModified}`;
    const seen = new Set(have.map(key));
    onFile?.([...have, ...more.filter((f) => !seen.has(key(f)) && seen.add(key(f)))]);
  };
  const remove = (f) => {
    const left = file.filter((x) => x !== f);
    onFile?.(left.length ? left : null);
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };
  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };
  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (multiple && folders && e.dataTransfer.items?.length) {
      // read the entries now: they're gone once this event is over
      const entries = [...e.dataTransfer.items].map((i) => i.webkitGetAsEntry?.()).filter(Boolean);
      droppedFiles(entries).then((all) => add(all.filter((f) => accepts(f.name))));
      return;
    }
    if (multiple) {
      add([...(e.dataTransfer.files || [])].filter((f) => accepts(f.name)));
      return;
    }
    const dropped = e.dataTransfer.files?.[0];
    if (!dropped) return;
    if (!accepts(dropped.name)) return;
    onFile?.(dropped);
  };
  const picked = multiple ? (file?.length ? file : null) : file;
  const pickedName = !picked ? null : !multiple ? picked.name : `${picked.length} picked: drop or click to add more`;

  return (
    <>
    <div
      onClick={() => inputRef.current?.click()}
      onDragOver={handleDragOver}
      onDragEnter={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      style={{
        border: `1.5px dashed ${isDragging ? c.amber : picked ? c.teal : c.borderStrong}`,
        borderRadius: 4,
        padding: compact ? "14px 16px" : "26px 16px",
        textAlign: "center",
        color: picked ? c.textPrimary : c.textFaint,
        background: isDragging ? c.amberDim : "transparent",
        ...ui,
        fontSize: fs(13),
        marginBottom: 14,
        display: "flex",
        flexDirection: compact ? "row" : "column",
        alignItems: "center",
        justifyContent: "center",
        gap: compact ? 8 : 0,
        cursor: "pointer",
        transition: "background 0.1s ease, border-color 0.1s ease",
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        onChange={(e) => {
          if (multiple) add([...(e.target.files || [])]);
          else onFile?.(e.target.files?.[0] || null);
          e.target.value = ""; // so the same file can be picked again after it's taken off
        }}
        style={{ display: "none" }}
      />
      {folders && (
        <input
          ref={folderRef}
          type="file"
          webkitdirectory=""
          multiple
          onChange={(e) => {
            add([...(e.target.files || [])].filter((f) => accepts(f.name)));
            e.target.value = "";
          }}
          style={{ display: "none" }}
        />
      )}
      <Upload size={compact ? 14 : 20} color={isDragging ? c.amber : picked ? c.teal : c.textFaint} style={{ marginBottom: compact ? 0 : 8 }} />
      <div style={{ wordBreak: "break-word" }}>{picked ? pickedName : isDragging ? (multiple ? "Drop them" : "Drop it") : label}</div>
      {folders && !isDragging && (
        <button
          type="button"
          data-testid="dropzone-choose-folder"
          onClick={(e) => {
            e.stopPropagation(); // not the file picker as well
            folderRef.current?.click();
          }}
          style={{ ...ui, fontSize: fs(12), background: "none", border: "none", color: c.amber, textDecoration: "underline", cursor: "pointer", marginTop: 6, padding: 0 }}
        >
          or choose a folder
        </button>
      )}
    </div>
    {multiple && picked && (
      <div data-testid="dropzone-picked" style={{ marginTop: -6, marginBottom: 14, maxHeight: 220, overflowY: "auto", border: `1px solid ${c.border}`, borderRadius: 4 }}>
        {picked.map((f, i) => (
          <div
            key={`${folderPathOf(f)}|${i}`}
            data-testid="dropzone-picked-file"
            style={{ display: "flex", alignItems: "center", gap: 10, padding: "4px 6px 4px 10px", borderTop: i ? `1px solid ${c.border}` : "none" }}
          >
            <span style={monoText(12, c.textPrimary, { flex: 1, minWidth: 0, overflowWrap: "anywhere" })}>{folderPathOf(f)}</span>
            <span style={uiText(12, c.textFaint, { whiteSpace: "nowrap" })}>{formatBytes(f.size)}</span>
            <TrashButton onClick={() => remove(f)} title={`Take ${f.name} off: it isn't uploaded`} />
          </div>
        ))}
      </div>
    )}
    </>
  );
}

export function FieldSelect({ label, options, placeholder, value, onChange }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={uiText(12, c.textFaint, { marginBottom: 5 })}>{label}</div>
      <select
        value={value ?? ""}
        onChange={(e) => onChange?.(e.target.value)}
        style={{
          width: "100%",
          background: c.panelAlt,
          border: `1px solid ${c.border}`,
          borderRadius: 4,
          color: c.textPrimary,
          padding: "8px 10px",
          fontSize: fs(13),
          ...ui,
        }}
      >
        <option value="" disabled>
          {placeholder}
        </option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

export function SegmentedToggle({ options, value, onChange }) {
  return (
    <div style={{ display: "flex", gap: 6, marginBottom: 14 }}>
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          style={{
            ...ui,
            fontSize: fs(12),
            padding: "6px 12px",
            borderRadius: 4,
            cursor: "pointer",
            border: `1px solid ${value === o.value ? c.amber : c.border}`,
            background: value === o.value ? c.amberDim : "transparent",
            color: value === o.value ? c.amber : c.textMuted,
          }}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function TextField({ label, value, onChange, placeholder, type = "text", disabled = false }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={uiText(12, c.textFaint, { marginBottom: 5 })}>{label}</div>
      <input
        type={type}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete={type === "password" ? "new-password" : "off"}
        style={{
          width: "100%",
          background: c.panelAlt,
          border: `1px solid ${c.border}`,
          borderRadius: 4,
          color: c.textPrimary,
          padding: "8px 10px",
          fontSize: fs(13),
          opacity: disabled ? 0.6 : 1,
          ...ui,
        }}
      />
    </div>
  );
}
