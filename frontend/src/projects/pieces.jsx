import { useState } from "react";
import { ChevronDown, FolderInput } from "lucide-react";
import { c, fs, ui, fixed } from "../theme.js";
import { useData } from "../data.jsx";
import { useAction } from "../hooks/useAction.js";
import { nameCollator } from "../lib/order.js";
import { ConfirmDialog, Modal } from "../components/common/dialogs.jsx";
import { SearchBox } from "../components/common/fields.jsx";
import { Row, Thumb } from "../components/common/ui.jsx";
import { monoText, panelBox, primaryButton, toolButton, uiText } from "../styles.js";
import { plural } from "../lib/format.js";
import { searchWords } from "../lib/search.jsx";

// What a project's page is built from: the pieces its sections share


// What an empty section (or list) says, in a slim box
export function EmptyBox({ children }) {
  return <div style={panelBox({ padding: "7px 12px", ...uiText(13, c.textFaint, { lineHeight: 1.5 }) })}>{children}</div>;
}

// A card on a project's page: a slim heading (what's on the left: `lead` (have / need), an icon, the name and its tags;
// the rest on the right) and what's under it. In a narrow window the right side moves onto a second line rather than
// squeezing the name.
export function Card({ testId, dataAttrs, heading, children }) {
  return (
    <div data-testid={testId} {...dataAttrs} style={{ border: `1px solid ${c.border}`, borderRadius: 4, overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, rowGap: 4, flexWrap: "wrap", padding: "5px 8px 5px 12px", background: c.panelAlt }}>
        {heading}
      </div>
      {children}
    </div>
  );
}

// The left of a card's heading: `lead`, the icon, the name (cut short with "…", the whole of it on hover; `name` may be
// a link), and its tags. It asks for room for some of the name besides the lead and tags, so in a narrow window the
// buttons on the right go to a second line before the name is squeezed away; the tags never shrink.
export function CardTitle({ lead, Icon, name, title, testId, tags }) {
  return (
    <span style={{ display: "flex", alignItems: "center", gap: 8, flex: `1 1 ${lead ? 400 : 240}px`, minWidth: 0 }}>
      {lead}
      <Icon size={14} color={c.textFaint} style={{ flexShrink: 0 }} />
      {typeof name === "string" ? (
        <span data-testid={testId} title={title || name} style={nameStyle()}>
          {name}
        </span>
      ) : (
        name
      )}
      {tags && <span style={{ display: "flex", gap: 6, flexShrink: 0 }}>{tags}</span>}
    </span>
  );
}

export const nameStyle = (extra) =>
  monoText(13, c.heading, { minWidth: "4em", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", ...extra });

// "In Models": a model or 3MF used by the project, which IS the one in the rest of Farmhand (not a copy)
export function InModelsTag({ title }) {
  return (
    <span title={title} style={uiText(11, c.textMuted, { border: `1px solid ${c.borderStrong}`, borderRadius: 3, padding: "0 6px", whiteSpace: "nowrap" })}>
      In Models
    </span>
  );
}

// "Project only", boxed in purple: on an STL or 3MF a project keeps for itself (uploaded to it, not put in Models)
export function ProjectOnlyTag() {
  return (
    <span
      data-testid="project-only-tag"
      title="Uploaded to this project only: not in Models, and deleted with the project"
      style={uiText(11, c.projectOnly, { border: `1px solid ${c.projectOnly}`, borderRadius: 3, padding: "0 6px", fontWeight: 600, whiteSpace: "nowrap" })}
    >
      Project only
    </span>
  );
}

// "N older": shows or hides a card's older versions (they start folded away)
export function OlderToggle({ count, open, onToggle, testId, controlsId }) {
  if (count === 0) return null;
  const words = plural(count, "older version");
  return (
    <button
      data-testid={testId}
      aria-expanded={open}
      aria-controls={controlsId}
      onClick={onToggle}
      title={open ? `Hide ${words}` : `Show ${words}`}
      style={toolButton(12, { whiteSpace: "nowrap", flexShrink: 0 })}
    >
      <ChevronDown size={12} style={{ transform: open ? "rotate(180deg)" : "none", transition: "transform 0.12s ease" }} />
      {count} older
    </button>
  );
}

// A heading's plain button: an icon and words
export function HeadingButton({ testId, Icon, label, title, onClick }) {
  return (
    <button data-testid={testId} onClick={onClick} title={title} style={toolButton(12, { whiteSpace: "nowrap", flexShrink: 0 })}>
      {Icon && <Icon size={12} />}
      {label}
    </button>
  );
}

// An STL's Move… button: which of the project's sub-components it's in
export function MoveButton({ testId, onClick }) {
  return <HeadingButton testId={testId} Icon={FolderInput} label="Move…" title="Move it to another sub-component" onClick={onClick} />;
}

// Taking something out of the project (it stays where it is: nothing is deleted), asked first. `label` is the button's
// word ("Take out", "Remove"); `children` the question.
export function TakeOutButton({ testId, label = "Take out", title = "Take it out of this project", dialogTitle = "Take out of project", confirmLabel = "Take it out", onConfirm, children }) {
  const [asking, setAsking] = useState(false);
  return (
    <>
      <button data-testid={testId} onClick={() => setAsking(true)} title={title} style={toolButton(12, { whiteSpace: "nowrap" })}>
        {label}
      </button>
      {asking && (
        <ConfirmDialog title={dialogTitle} confirmLabel={confirmLabel} tone="warn" onClose={() => setAsking(false)} onConfirm={onConfirm}>
          {children}
        </ConfirmDialog>
      )}
    </>
  );
}

// Picking things to add to a project: everything offered, searchable (each item's `search` text), sorted by name. Each
// is added at once (`add(id)` answers the project), and the dialog stays open for the next until Done.
// items: [{ id, name, sub, thumb, plateGrid, mono }]; noun: "models" ("No models match.")
export function PickDialog({ title, width = 560, noun, searchPlaceholder, items, allTaken, add, pickTestId, onClose }) {
  const { putProject } = useData();
  const [query, setQuery] = useState("");
  const { busy, error, run } = useAction();
  const words = searchWords(query);
  const shown = items
    .filter((x) => words.every((w) => (x.search || x.name).toLowerCase().includes(w)))
    .sort((a, b) => nameCollator.compare(a.name, b.name));
  return (
    <Modal title={title} onClose={onClose} width={width}>
      {searchPlaceholder && (
        <SearchBox value={query} onChange={setQuery} placeholder={searchPlaceholder} label={`Search ${noun}`} style={{ marginBottom: 12 }} />
      )}
      {error && <div style={uiText(12, c.amber, { marginBottom: 10 })}>{error}</div>}
      <div style={panelBox({ overflow: "hidden", maxHeight: "50vh", overflowY: "auto" })}>
        {shown.length === 0 ? (
          <div style={{ padding: 16, ...uiText(13, c.textFaint) }}>{items.length === 0 ? allTaken : `No ${noun} match.`}</div>
        ) : (
          shown.map((x) => (
            <Row key={x.id} hoverable={false}>
              {x.Icon ? <x.Icon size={15} color={c.textFaint} /> : <Thumb src={x.thumb} size={36} plateGrid={x.plateGrid} background={x.plateGrid ? undefined : fixed.preview} placeholderIcon />}
              <div style={{ flex: 1, minWidth: 0, marginLeft: x.Icon ? 10 : 12 }}>
                <div style={x.mono ? monoText(12, c.textPrimary, { overflowWrap: "anywhere" }) : uiText(13, c.textPrimary, { overflowWrap: "anywhere" })}>{x.name}</div>
                {x.sub && <div style={uiText(12, c.textFaint, { marginTop: 2 })}>{x.sub}</div>}
              </div>
              <button
                disabled={busy}
                data-testid={`${pickTestId}-${x.id}`}
                onClick={() => run(async () => putProject(await add(x.id)))}
                style={{ ...primaryButton(busy), fontSize: fs(12), padding: "5px 12px", marginLeft: 12, ...ui }}
              >
                Add
              </button>
            </Row>
          ))
        )}
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 12 }}>
        <button onClick={onClose} style={toolButton(13)}>
          Done
        </button>
      </div>
    </Modal>
  );
}

// A version's line under a card's heading (a model's or a 3MF's from the rest of Farmhand): its preview, number, file
// name, date and notes, and what goes on the right
export function VersionLine({ testId, ver, isLatest, thumb, plateGrid = false, filename, details, children }) {
  return (
    <div data-testid={testId} data-version={ver.v} style={{ display: "flex", alignItems: "center", gap: 14, padding: "10px 16px", borderTop: `1px solid ${c.border}`, flexWrap: "wrap" }}>
      <Thumb src={thumb} size={64} plateGrid={plateGrid} background={plateGrid ? undefined : fixed.preview} placeholderIcon />
      <span style={monoText(12, isLatest ? c.amber : c.textFaint, { width: 30 })}>v{ver.v}</span>
      <div style={{ flex: "1 1 220px", minWidth: 0 }}>
        {filename && <div style={monoText(12, c.textPrimary, { overflowWrap: "anywhere" })}>{filename}</div>}
        <div style={uiText(12, c.textFaint, { marginTop: filename ? 3 : 0 })}>{details}</div>
      </div>
      <div style={{ marginLeft: "auto" }}>{children}</div>
    </div>
  );
}
