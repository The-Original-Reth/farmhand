import { useEffect, useRef, useState } from "react";
import { Check, Pencil, X } from "lucide-react";
import { c } from "../theme.js";
import { uiText } from "../styles.js";
import { useAction } from "../hooks/useAction.js";

// A file's name with a pencil beside it: click the pencil to rename it in place (Enter saves, Escape cancels).
// Only the part before the extension can be edited: the extension (.stl, .3mf...) is shown beside the box and always
// kept. The name is what Farmhand shows, searches by and downloads as; the stored file keeps its own name.
// onSave(newName) saves it and puts the result in the page's data.
// `children` is how the name normally looks (e.g. with search words highlighted); `textStyle` styles the edit box.
const splitExtension = (name, fallback) => {
  const m = /^(.*?)(\.[^./\\]+)$/.exec(name);
  return m && m[1] ? [m[1], m[2]] : [name, fallback];
};
// `boxed` draws a box around the name, in the 3MF file name colour (c.fileName, set on the Appearance page).
export function EditableName({ value, onSave, label, textStyle, testId, extension: fallbackExtension, boxed = false, children }) {
  const [stem, extension] = splitExtension(value, fallbackExtension);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(stem);
  const { busy, error, setError, run } = useAction();
  const [hover, setHover] = useState(false);
  const inputRef = useRef(null);
  const stop = (e) => e.stopPropagation(); // the name often sits in a header that folds or opens when clicked
  // After a refused save, put the cursor back in the box (it's disabled while saving, which loses the focus)
  useEffect(() => {
    if (error && !busy) inputRef.current?.focus();
  }, [error, busy]);

  const start = (e) => {
    stop(e);
    setText(stem);
    setError(null);
    setEditing(true);
  };
  const cancel = () => {
    setEditing(false);
    setError(null);
  };
  const save = async () => {
    if (text.trim() === stem) return cancel();
    await run(async () => {
      await onSave(text.trim() + extension); // the extension always stays as it was; onSave updates the page's data
      setEditing(false);
    });
  };

  if (!editing) {
    return (
      <span data-testid={testId} style={{ display: "inline-flex", alignItems: "center", gap: 6, minWidth: 0 }}>
        {boxed ? (
          <span
            data-testid={testId && `${testId}-box`}
            style={{ display: "inline-block", minWidth: 0, overflowWrap: "anywhere", border: `1px solid ${c.borderStrong}`, borderRadius: 3, background: c.panel, padding: "2px 7px", color: c.fileName }}
          >
            {children ?? value}
          </span>
        ) : (
          children ?? value
        )}
        <button
          data-testid={testId && `${testId}-edit`}
          onClick={start}
          onMouseEnter={() => setHover(true)}
          onMouseLeave={() => setHover(false)}
          title={`Rename ${label}`}
          aria-label={`Rename ${label}`}
          style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 20, height: 20, padding: 0, flexShrink: 0, background: "none", border: "none", cursor: "pointer", color: hover ? c.amber : c.textFaint }}
        >
          <Pencil size={12} />
        </button>
      </span>
    );
  }
  const iconButton = { display: "inline-flex", alignItems: "center", justifyContent: "center", width: 24, height: 24, padding: 0, flexShrink: 0, borderRadius: 3, cursor: busy ? "default" : "pointer" };
  return (
    <span onClick={stop} style={{ display: "inline-flex", flexDirection: "column", gap: 3, minWidth: 0, flex: "1 1 auto", width: "100%", maxWidth: 560 }}>
      <span style={{ display: "flex", alignItems: "center", gap: 4, width: "100%" }}>
        <input
          ref={inputRef}
          data-testid={testId && `${testId}-input`}
          autoFocus
          value={text}
          disabled={busy}
          onChange={(e) => setText(e.target.value)}
          onFocus={(e) => e.target.select()}
          onKeyDown={(e) => {
            if (e.key === "Enter") save();
            if (e.key === "Escape") cancel();
          }}
          aria-label={`New name for ${label}, without ${extension}`}
          spellCheck={false}
          style={{ ...textStyle, flex: 1, minWidth: 220, background: c.panel, border: `1px solid ${error ? c.danger : c.amber}`, borderRadius: 3, padding: "3px 6px", color: c.heading, outline: "none" }}
        />
        <span data-testid={testId && `${testId}-extension`} title="The extension always stays" style={{ ...textStyle, color: c.textMuted, flexShrink: 0 }}>
          {extension}
        </span>
        <button data-testid={testId && `${testId}-save`} onClick={save} disabled={busy} title="Save (Enter)" aria-label="Save name" style={{ ...iconButton, border: `1px solid ${c.amber}`, background: c.amber, color: c.onAccent }}>
          <Check size={13} />
        </button>
        <button onClick={cancel} disabled={busy} title="Cancel (Escape)" aria-label="Cancel renaming" style={{ ...iconButton, border: `1px solid ${c.border}`, background: "none", color: c.textMuted }}>
          <X size={13} />
        </button>
      </span>
      {error && <span style={uiText(11, c.danger)}>{error}</span>}
    </span>
  );
}
