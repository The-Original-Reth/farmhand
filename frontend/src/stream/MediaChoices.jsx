import { useRef, useState } from "react";
import { c, fixed, ui } from "../theme.js";
import { headerButton, uiText } from "../styles.js";
import { orderSlideshow, scanStreamFolder, createSlideshow, removeSlideshow, removeSlideshowPicture, removeStreamPicture, slideshowPictureUrl, uploadSlideshowPictures, uploadStreamPictures } from "../api.js";
import { box, help, label12 } from "./editorFields.js";

// A card's picture or slideshow, from the stream folder, in the square editor (SquareEditor.jsx): choosing,
// uploading and deleting them, and where a slideshow's folder is, to open in File Explorer.

// One of the stream folder's single pictures, or a new one uploaded; Delete picture removes its file
export function PictureChoice({ card, setCard, media, ask, busy }) {
  const input = useRef(null);
  const [removing, setRemoving] = useState(false);
  const upload = async (files) => {
    if (!files.length) return;
    const before = new Set(media.images);
    const p = await ask("picture", () => uploadStreamPictures(files));
    input.current.value = "";
    const added = p?.media.images.find((n) => !before.has(n));
    if (added) setCard({ image: added, slideshow: null });
  };
  return (
    <>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <select data-testid="stream-square-picture" value={card.image || ""} onChange={(e) => setCard({ image: e.target.value || null, slideshow: null })} style={box()}>
          <option value="">{media.images.length ? "Choose a picture…" : "No pictures yet"}</option>
          {card.image && !media.images.includes(card.image) && <option value={card.image}>{card.image} (not in the folder)</option>}
          {media.images.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
        <input ref={input} data-testid="stream-picture-file" type="file" multiple accept="image/png,image/jpeg,image/webp" style={{ display: "none" }} onChange={(e) => upload([...e.target.files])} />
        <button type="button" data-testid="stream-picture-upload" onClick={() => input.current.click()} disabled={!!busy || !!media.error} style={headerButton()}>
          {busy === "picture" ? "Uploading…" : "Upload picture"}
        </button>
        <ScanFolder ask={ask} busy={busy} media={media} />
        {card.image && media.images.includes(card.image) && !removing && (
          <button type="button" onClick={() => setRemoving(true)} disabled={!!busy} style={headerButton()}>
            Delete picture
          </button>
        )}
      </div>
      {removing && (
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          <span style={uiText(12, c.textMuted)}>Delete “{card.image}” from the stream folder?</span>
          <button type="button" onClick={() => ask("picture", () => removeStreamPicture(card.image)).then(() => setRemoving(false))} style={{ ...headerButton(), color: c.danger, borderColor: c.danger }}>
            Delete
          </button>
          <button type="button" onClick={() => setRemoving(false)} style={headerButton()}>
            Keep
          </button>
        </div>
      )}
      <div style={help}>PNG, JPEG or WebP, fitted to the square. Pictures copied into the stream folder's images folder show up here too.</div>
    </>
  );
}

// A slideshow (a folder of pictures in the stream folder, shown in turn): chosen from the list, and five buttons. New
// slideshow (asks its name), Add pictures (into the one chosen), Open folder (where its folder is, to open in File
// Explorer), Rename (its folder on the server too; squares showing it follow) and Delete slideshow. Then how
// long each picture shows, and its pictures, each with its own Delete.
export function SlideshowChoice({ card, setCard, media, ask, busy, slide, onRename }) {
  const input = useRef(null);
  const [opening, setOpening] = useState(false); // showing where the folder is, for File Explorer
  const [name, setName] = useState(null); // the new slideshow's name being typed; null when not making one
  const [removing, setRemoving] = useState(null); // "show" | a picture's name, asking "Delete?"
  const [renaming, setRenaming] = useState(null); // the chosen slideshow's new name being typed; null when not renaming
  const [moving, setMoving] = useState(null); // the picture being dragged to a new place
  const [overPic, setOverPic] = useState(null); // the picture it would take the place of
  const show = media.slideshows.find((x) => x.name === card.slideshow) || null;
  // the picture dragged takes the place of the one it's dropped on (the slideshow's order is kept in its folder)
  const moveTo = (target) => {
    const from = show.images.indexOf(moving);
    const to = show.images.indexOf(target);
    setMoving(null);
    setOverPic(null);
    if (from < 0 || to < 0 || from === to) return;
    const order = [...show.images];
    order.splice(to, 0, order.splice(from, 1)[0]);
    ask("picture", () => orderSlideshow(show.name, order));
  };
  const create = async () => {
    const n = (name || "").trim();
    if (!n) return;
    const p = await ask("picture", () => createSlideshow(n));
    if (p?.media.slideshows.some((x) => x.name === n)) {
      setCard({ slideshow: n, image: null });
      setName(null);
    }
  };
  const rename = async () => {
    const n = (renaming || "").trim();
    if (!n || !show || !onRename) return;
    if (n === show.name) return setRenaming(null);
    const p = await onRename(show.name, n);
    if (p?.media.slideshows.some((x) => x.name === n)) {
      setCard({ slideshow: n, image: null });
      setRenaming(null);
    }
  };
  const addPictures = async (files) => {
    input.current.value = "";
    if (files.length && show) await ask("picture", () => uploadSlideshowPictures(show.name, files));
  };
  const off = !!busy || !!media.error;
  return (
    <>
      <select data-testid="stream-square-slideshow" value={card.slideshow || ""} onChange={(e) => (setCard({ slideshow: e.target.value || null, image: null }), setRemoving(null), setRenaming(null))} style={box()}>
        <option value="">{media.slideshows.length ? "Choose a slideshow…" : "No slideshows yet"}</option>
        {card.slideshow && !show && <option value={card.slideshow}>{card.slideshow} (not in the folder)</option>}
        {media.slideshows.map((x) => <option key={x.name} value={x.name}>{x.name} ({x.images.length})</option>)}
      </select>
      <input ref={input} data-testid="stream-slideshow-file" type="file" multiple accept="image/png,image/jpeg,image/webp" style={{ display: "none" }} onChange={(e) => addPictures([...e.target.files])} />
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        <button type="button" data-testid="stream-slideshow-new" onClick={() => (setName(""), setRemoving(null), setRenaming(null))} disabled={off} style={headerButton()}>
          New slideshow
        </button>
        <button
          type="button" data-testid="stream-slideshow-add" onClick={() => input.current.click()} disabled={off || !show} style={headerButton()}
          title={show ? `Add pictures to “${show.name}”` : "Choose a slideshow first"}
        >
          Add pictures
        </button>
        <button
          type="button" data-testid="stream-slideshow-open-folder" onClick={() => setOpening(!opening)} style={{ ...headerButton(), color: opening ? c.amber : c.textMuted }}
          title="Where the slideshow's folder is, to open it in File Explorer"
        >
          Open folder
        </button>
        {onRename && (
          <button
            type="button" data-testid="stream-slideshow-rename" onClick={() => (setRenaming(show.name), setName(null), setRemoving(null))} disabled={off || !show} style={headerButton()}
            title={show ? `Rename “${show.name}”: its folder on the server too` : "Choose a slideshow first"}
          >
            Rename
          </button>
        )}
        <button type="button" data-testid="stream-slideshow-delete" onClick={() => (setRemoving("show"), setRenaming(null))} disabled={off || !show} style={headerButton()}>
          Delete slideshow
        </button>
        <ScanFolder ask={ask} busy={busy} media={media} />
        {busy === "picture" && <span style={uiText(12, c.textFaint)}>Working…</span>}
      </div>
      {opening && <OpenFolder media={media} show={show} />}
      {name !== null && (
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          <input
            data-testid="stream-slideshow-name" autoFocus value={name} maxLength={100} placeholder="The new slideshow's name" onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => (e.key === "Enter" ? create() : e.key === "Escape" && setName(null))} style={{ ...box(), width: 200 }}
          />
          <button type="button" data-testid="stream-slideshow-create" onClick={create} disabled={off || !name.trim()} style={headerButton()}>
            Make it
          </button>
          <button type="button" onClick={() => setName(null)} style={headerButton()}>
            Cancel
          </button>
        </div>
      )}
      {renaming !== null && show && (
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          <input
            data-testid="stream-slideshow-new-name" autoFocus value={renaming} maxLength={100} placeholder="The slideshow's new name" onChange={(e) => setRenaming(e.target.value)}
            onFocus={(e) => e.target.select()} onKeyDown={(e) => (e.key === "Enter" ? rename() : e.key === "Escape" && setRenaming(null))} style={{ ...box(), width: 200 }}
          />
          <button type="button" data-testid="stream-slideshow-rename-save" onClick={rename} disabled={off || !renaming.trim()} style={headerButton()}>
            Rename
          </button>
          <button type="button" onClick={() => setRenaming(null)} style={headerButton()}>
            Cancel
          </button>
          <span style={uiText(12, c.textFaint)}>Its folder on the server is renamed too, and squares and saved layouts showing it follow.</span>
        </div>
      )}
      {removing === "show" && show && (
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          <span style={uiText(12, c.textMuted)}>Delete the slideshow “{show.name}” and its {show.images.length} pictures?</span>
          <button type="button" onClick={() => ask("picture", () => removeSlideshow(show.name)).then(() => setRemoving(null))} style={{ ...headerButton(), color: c.danger, borderColor: c.danger }}>
            Delete
          </button>
          <button type="button" onClick={() => setRemoving(null)} style={headerButton()}>
            Keep
          </button>
        </div>
      )}
      <label style={label12}>
        Show each picture for
        <input
          data-testid="stream-slideshow-seconds" type="number" min={3} max={3600} value={card.seconds}
          onChange={(e) => setCard({ seconds: e.target.value === "" ? "" : Number(e.target.value) })} style={{ ...box(), width: 80 }}
        />
        seconds <span style={uiText(11, c.textFaint)}>(3 to 3600)</span>
      </label>
      {show && show.images.length > 0 && slide && <SlideControls show={show} slide={slide} />}
      {show && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {show.images.length === 0 && <span style={uiText(12, c.textFaint)}>No pictures in it yet: Add pictures or Open folder.</span>}
          {show.images.map((n, i) => (
            <div
              key={n} data-testid="stream-slide-thumb" draggable={!busy}
              onDragStart={(e) => {
                e.dataTransfer.effectAllowed = "move";
                e.dataTransfer.setData("text/plain", n);
                setMoving(n);
              }}
              onDragEnter={() => moving && setOverPic(n)}
              onDragOver={(e) => moving && e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                moveTo(n);
              }}
              onDragEnd={() => (setMoving(null), setOverPic(null))}
              style={{ width: 96, display: "flex", flexDirection: "column", gap: 3, opacity: moving === n ? 0.4 : 1, cursor: busy ? "default" : "grab" }}
            >
              <div
                style={{
                  position: "relative", height: 54, background: fixed.pictureThumb, borderRadius: 3, display: "flex", alignItems: "center", justifyContent: "center",
                  outline: overPic === n && moving !== n ? `2px solid ${c.amber}` : "none",
                }}
                title={`${i + 1}. ${n}: drag onto another picture to move it there`}
              >
                <img src={slideshowPictureUrl(show.name, n)} alt={n} draggable={false} style={{ maxWidth: "90%", maxHeight: "90%", objectFit: "contain", pointerEvents: "none" }} />
                <span style={{ position: "absolute", left: 3, top: 2, ...uiText(10, c.textMuted), background: fixed.pictureThumb, padding: "0 3px", borderRadius: 2 }}>{i + 1}</span>
              </div>
              {removing === n ? (
                <div style={{ display: "flex", gap: 3 }}>
                  <button type="button" onClick={() => ask("picture", () => removeSlideshowPicture(show.name, n)).then(() => setRemoving(null))} style={{ ...headerButton(), color: c.danger, borderColor: c.danger, padding: "0 5px" }}>
                    Delete
                  </button>
                  <button type="button" onClick={() => setRemoving(null)} style={{ ...headerButton(), padding: "0 5px" }}>
                    Keep
                  </button>
                </div>
              ) : (
                <button type="button" onClick={() => setRemoving(n)} title={n} style={{ ...headerButton(), justifyContent: "center", padding: "0 5px" }}>
                  Delete
                </button>
              )}
            </div>
          ))}
        </div>
      )}
      <div style={help}>
        Each slideshow is a folder in the stream folder's slideshows folder: its pictures show one after another, round and round,
        in the order above (drag a picture onto another to move it there; new ones go on the end). Pictures copied into it yourself count too. One slideshow can be in several squares.
      </div>
    </>
  );
}

// Where a slideshow's folder is (or the slideshows folder, with none chosen), to open in File Explorer: a web page can't
// open a window on this computer itself, so it's shown as Windows reaches it over the network (\\server\share\...) to
// copy and paste into File Explorer's address bar. A stream folder that isn't on a network share can't be reached so.
function OpenFolder({ media, show }) {
  const field = useRef(null);
  const [copied, setCopied] = useState(false);
  const rest = show ? `slideshows\\${show.name}` : "slideshows";
  const where = media.windows_path ? `${media.windows_path}\\${rest}` : null;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(where); // only on https or this computer's own address
    } catch {
      field.current.select(); // elsewhere, the browser's own copy of what's selected
      document.execCommand("copy");
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  if (!where) {
    return (
      <div style={uiText(12, c.textMuted, { lineHeight: 1.5 })}>
        The stream folder is in Farmhand's own storage (<span style={{ ...ui, fontFamily: "monospace" }}>{media.path}</span>), not on a network share, so
        Windows can't open it. Choose a stream folder on your NAS in Settings to open it from here.
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <input
          ref={field} data-testid="stream-slideshow-path" readOnly value={where} onFocus={(e) => e.target.select()}
          style={{ ...box(), flex: 1, minWidth: 0, fontFamily: "monospace" }}
        />
        <button type="button" data-testid="stream-slideshow-copy-path" onClick={copy} style={headerButton()}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <div style={uiText(11, c.textFaint, { lineHeight: 1.5 })}>
        Paste it into File Explorer's address bar (a web page can't open File Explorer itself). Pictures you put in it show up here.
      </div>
    </div>
  );
}

// Scan folder: the stream folder read again, for pictures copied in or taken out by hand (Farmhand doesn't keep looking)
function ScanFolder({ ask, busy, media }) {
  return (
    <button
      type="button" data-testid="stream-scan-folder" onClick={() => ask("picture", scanStreamFolder)} disabled={!!busy} style={headerButton()}
      title="Look in the stream folder again, for pictures copied in or taken out by hand"
    >
      {busy === "picture" ? "Working…" : media.error ? "Try the folder again" : "Scan folder"}
    </button>
  );
}

// Going through a slideshow on the editor's canvas (and the preview's square with it): Play (round on its own), Stop (holds
// the picture on show, to move or resize it, or write its own words), Back and Next; and which picture is on show
function SlideControls({ show, slide }) {
  const n = show.images.length;
  const at = slide.at % n;
  return (
    <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
      {slide.playing ? (
        <button type="button" data-testid="stream-slideshow-stop" onClick={slide.stop} style={headerButton()}>
          Stop
        </button>
      ) : (
        <button type="button" data-testid="stream-slideshow-play" onClick={slide.play} style={headerButton()}>
          Play
        </button>
      )}
      <button type="button" data-testid="stream-slideshow-back" onClick={() => (slide.stop(), slide.go((at - 1 + n) % n))} disabled={n < 2} style={headerButton()}>
        Back
      </button>
      <button type="button" data-testid="stream-slideshow-next" onClick={() => (slide.stop(), slide.go((at + 1) % n))} disabled={n < 2} style={headerButton()}>
        Next
      </button>
      <span data-testid="stream-slideshow-at" style={uiText(12, c.textMuted)}>
        Picture {at + 1} of {n}: {show.images[at]}
      </span>
    </div>
  );
}
