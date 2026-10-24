import React from "react";
import { c, ui, mono, fs } from "./theme.js";
import { PRESETS, FONTS, SIZES, DEFAULT_APPEARANCE } from "./palettes.js";

// The Appearance controls, as a section of the Storage page. The page re-renders in the new look as each
// choice is made, so the page itself is the preview; the sample at the bottom just shows the kinds of
// text and colour used around the app side by side.

function Heading({ children }) {
  return (
    <div style={{ ...ui, fontSize: fs(11), color: c.textMuted, textTransform: "uppercase", letterSpacing: 0.5, margin: "18px 0 8px" }}>
      {children}
    </div>
  );
}

// A little picture of a scheme, drawn in that scheme's own colours
function SchemeCard({ preset, selected, onPick }) {
  const p = preset.colors;
  return (
    <button
      data-testid={`scheme-${preset.id}`}
      role="radio"
      aria-checked={selected}
      onClick={onPick}
      style={{
        textAlign: "left", padding: 6, borderRadius: 6, cursor: "pointer", background: "transparent",
        border: `2px solid ${selected ? c.amber : c.border}`, color: c.textPrimary, ...ui,
      }}
    >
      <div style={{ display: "flex", height: 54, borderRadius: 3, overflow: "hidden", background: p.bg, border: `1px solid ${p.border}` }}>
        <div style={{ width: 16, background: p.panel, borderRight: `1px solid ${p.border}` }} />
        <div style={{ flex: 1, padding: "7px 8px", display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ height: 4, width: "42%", borderRadius: 2, background: p.heading }} />
          <div style={{ height: 3, width: "72%", borderRadius: 2, background: p.textMuted }} />
          <div style={{ height: 3, width: "56%", borderRadius: 2, background: p.textFaint }} />
          <div style={{ display: "flex", gap: 4, marginTop: 2 }}>
            <div style={{ height: 6, width: 16, borderRadius: 3, background: p.amber }} />
            <div style={{ height: 6, width: 16, borderRadius: 3, background: p.teal }} />
          </div>
        </div>
      </div>
      <div style={{ fontSize: fs(13), marginTop: 6, color: c.heading }}>{preset.name}</div>
      <div style={{ fontSize: fs(11), color: c.textFaint, lineHeight: 1.4 }}>{preset.note}</div>
    </button>
  );
}

function ChoiceButton({ id, selected, onPick, children, style }) {
  return (
    <button
      data-testid={id}
      role="radio"
      aria-checked={selected}
      onClick={onPick}
      style={{
        cursor: "pointer", borderRadius: 4, border: `1px solid ${selected ? c.amber : c.border}`,
        background: selected ? c.amberDim : "transparent", color: selected ? c.heading : c.textMuted, ...ui, ...style,
      }}
    >
      {children}
    </button>
  );
}

function Chip({ fg, bg, border, children }) {
  return (
    <span style={{ ...ui, fontSize: fs(12), color: fg, background: bg, border: `1px solid ${border}`, borderRadius: 3, padding: "2px 8px" }}>{children}</span>
  );
}

// Where the choice is being kept, in words
function saveStatusLine(saveState, locationPath) {
  if (!saveState || saveState.phase === "idle") {
    return locationPath
      ? { tone: "faint", text: "Kept on the server, with a copy in your settings folder." }
      : { tone: "faint", text: "Kept on the server, so every browser shows the same look. Choose a settings folder on the Storage page to keep a copy on the network too." };
  }
  if (saveState.phase === "saving") return { tone: "faint", text: "Saving…" };
  if (saveState.phase === "error") return { tone: "warn", text: `Couldn't save to the server (${saveState.message}). It's applied here but won't be remembered elsewhere.` };
  if (saveState.mirror && !saveState.mirror.skipped && !saveState.mirror.ok) {
    return { tone: "warn", text: `Saved on the server, but the copy in the settings folder couldn't be updated: ${saveState.mirror.error}` };
  }
  return {
    tone: "good",
    text: saveState.mirror && !saveState.mirror.skipped ? `Saved on the server and copied to ${saveState.mirror.path}.` : "Saved on the server.",
  };
}

export function AppearanceSection({ appearance, saved, onChange, onSave, onDiscard, saveState, locationPath }) {
  const set = (patch) => onChange({ ...appearance, ...patch });
  const preset = PRESETS.find((p) => p.id === appearance.scheme) || PRESETS[0];
  const dirty = ["scheme", "contrast", "font", "size"].some((k) => appearance[k] !== saved[k]);
  const saving = saveState?.phase === "saving";
  const status = dirty
    ? { tone: "warn", text: "Not saved yet. What you see is a preview: press Save to keep it. Leaving this page without saving undoes it." }
    : saveStatusLine(saveState, locationPath);

  return (
    <div data-testid="appearance-section" data-dirty={dirty ? "true" : "false"} style={{ border: `1px solid ${c.border}`, borderRadius: 4, background: c.panel, padding: 16, ...ui }}>
      <div style={{ fontSize: fs(15), color: c.heading, marginBottom: 2 }}>Appearance</div>
      <div style={{ fontSize: fs(12), color: c.textFaint, lineHeight: 1.5 }}>
        Colours, lettering and text size for the whole site. Changes show here as you make them; press Save to keep them.
      </div>

      <Heading>Colour scheme</Heading>
      <div role="radiogroup" aria-label="Colour scheme" style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8 }}>
        {PRESETS.map((p) => (
          <SchemeCard key={p.id} preset={p} selected={appearance.scheme === p.id} onPick={() => set({ scheme: p.id })} />
        ))}
      </div>

      <Heading>{preset.mode === "light" ? "Text contrast" : "Text brightness"}</Heading>
      <input
        data-testid="contrast-slider"
        type="range" min={0} max={100} step={1}
        value={appearance.contrast}
        onChange={(e) => set({ contrast: Number(e.target.value) })}
        aria-label={preset.mode === "light" ? "Text contrast" : "Text brightness"}
        style={{ width: "100%", accentColor: c.amber }}
      />
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: fs(11), color: c.textMuted, marginTop: 2 }}>
        <span>{preset.mode === "light" ? "Softer" : "Softer grey"}</span>
        <span data-testid="contrast-value" style={mono}>{appearance.contrast}%</span>
        <span>{preset.mode === "light" ? "Darker" : "Whiter"}</span>
      </div>

      <Heading>Font</Heading>
      <div role="radiogroup" aria-label="Font" style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 6 }}>
        {FONTS.map((f) => (
          <ChoiceButton
            key={f.id} id={`font-${f.id}`} selected={appearance.font === f.id} onPick={() => set({ font: f.id })}
            style={{ textAlign: "left", padding: "8px 10px", fontFamily: f.stack, fontSize: fs(14) }}
          >
            <span style={{ fontSize: fs(16), marginRight: 10 }}>Aa</span>
            {f.name}
            <span style={{ fontSize: fs(11), opacity: 0.8 }}> — {f.note}</span>
          </ChoiceButton>
        ))}
      </div>

      <Heading>Text size</Heading>
      <div role="radiogroup" aria-label="Text size" style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 6 }}>
        {SIZES.map((s) => (
          <ChoiceButton key={s.id} id={`size-${s.id}`} selected={appearance.size === s.id} onPick={() => set({ size: s.id })} style={{ padding: "8px 6px", fontSize: fs(13) }}>
            {s.name}
          </ChoiceButton>
        ))}
      </div>

      <Heading>Preview</Heading>
      <div data-testid="appearance-preview" style={{ border: `1px solid ${c.border}`, borderRadius: 4, background: c.bg, padding: 14 }}>
        <div style={{ fontSize: fs(15), color: c.heading, marginBottom: 2 }}>MMMini_GreatWhiteShark_v01.stl</div>
        <div style={{ fontSize: fs(13), color: c.textPrimary }}>Sliced for VT 1190 · 2 versions · PrusaSlicer 2.9.5</div>
        <div style={{ fontSize: fs(12), color: c.textMuted, marginTop: 2 }}>Sort by name · 3 models</div>
        <div style={{ fontSize: fs(11), color: c.textFaint, marginTop: 2 }}>Added Oct 23</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: 12 }}>
          <Chip fg={c.green} bg={c.greenDim} border={c.greenBorder}>ready</Chip>
          <Chip fg={c.amber} bg={c.amberDim} border={c.amberBorder}>0.18</Chip>
          <Chip fg={c.teal} bg={c.tealDim} border={c.tealBorder}>0.2</Chip>
          <span style={{ ...ui, fontSize: fs(13), background: c.amber, color: c.onAccent, borderRadius: 3, padding: "5px 12px", fontWeight: 600 }}>Upload</span>
          <span style={{ ...ui, fontSize: fs(13), background: c.danger, color: c.onDanger, borderRadius: 3, padding: "5px 12px", fontWeight: 600 }}>Delete</span>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginTop: 18, flexWrap: "wrap" }}>
        <div
          data-testid="appearance-save-status"
          style={{ fontSize: fs(12), lineHeight: 1.5, flex: 1, minWidth: 200, color: status.tone === "warn" ? c.amber : status.tone === "good" ? c.green : c.textFaint }}
        >
          {status.text}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button
            data-testid="appearance-reset"
            onClick={() => onChange({ ...DEFAULT_APPEARANCE })}
            style={{ background: "none", border: `1px solid ${c.border}`, borderRadius: 4, color: c.textMuted, cursor: "pointer", padding: "7px 12px", fontSize: fs(13), ...ui }}
          >
            Reset to defaults
          </button>
          <button
            data-testid="appearance-discard"
            onClick={onDiscard}
            disabled={!dirty}
            style={{ background: "none", border: `1px solid ${c.border}`, borderRadius: 4, color: dirty ? c.textPrimary : c.textFaint, cursor: dirty ? "pointer" : "default", opacity: dirty ? 1 : 0.55, padding: "7px 12px", fontSize: fs(13), ...ui }}
          >
            Discard changes
          </button>
          <button
            data-testid="appearance-save"
            onClick={onSave}
            disabled={!dirty || saving}
            style={{ background: dirty && !saving ? c.amber : c.panelAlt, border: `1px solid ${dirty && !saving ? c.amber : c.border}`, borderRadius: 4, color: dirty && !saving ? c.onAccent : c.textFaint, cursor: dirty && !saving ? "pointer" : "default", fontWeight: 600, padding: "7px 18px", fontSize: fs(13), ...ui }}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
