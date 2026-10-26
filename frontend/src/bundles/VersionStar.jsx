import { useState } from "react";
import { Star } from "lucide-react";
import { c } from "../theme.js";
import { setStarredVersion } from "../api.js";
import { useData } from "../data.jsx";

// Stars are real metal colours, not theme roles: the initial version is silver and the starred version is gold in
// every scheme (the theme's "amber" is blue or violet in some of them). Each has a darker edge so it holds up on
// light backgrounds.
const STAR_GOLD = "#F2C230";
const STAR_GOLD_EDGE = "#B8860B";
const STAR_SILVER = "#C9CDD3";
const STAR_SILVER_EDGE = "#868B93";

// The star beside a 3MF version's thumbnail. v1, the initial upload, is always silver. Every later version has an
// outline star; clicking one turns it gold, and only one version of a 3MF is gold at a time, so starring another
// moves it. Clicking the gold one clears it. The star changes at once; if the save fails it goes back and says why.
export function VersionStar({ bundle, ver }) {
  const { refresh } = useData();
  const [pending, setPending] = useState(undefined); // the starred version id being saved (null = clearing)
  const [error, setError] = useState(null);
  const [hover, setHover] = useState(false);

  if (ver.v === 1) {
    return <Star data-testid="initial-star" size={13} color={STAR_SILVER_EDGE} fill={STAR_SILVER} aria-label="Initial version" />;
  }

  const busy = pending !== undefined;
  const starred = (busy ? pending : bundle.starredVersionId) === ver.id;
  const label = error ? `Couldn't save the star: ${error}` : starred ? "Starred — click to un-star" : `Star v${ver.v}`;
  const toggle = async (e) => {
    e.stopPropagation();
    if (busy) return;
    const next = starred ? null : ver.id;
    setError(null);
    setPending(next);
    try {
      await setStarredVersion({ bundleId: bundle.id, versionId: next });
      await refresh();
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setPending(undefined);
    }
  };
  return (
    <button
      data-testid="version-star"
      data-starred={starred ? "true" : "false"}
      aria-pressed={starred}
      onClick={toggle}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      title={label}
      aria-label={label}
      style={{
        display: "flex", alignItems: "center", justifyContent: "center", width: 20, height: 20, padding: 0,
        border: "none", background: "none", cursor: busy ? "default" : "pointer",
        color: error ? c.danger : starred ? STAR_GOLD_EDGE : hover ? c.textMuted : c.textFaint,
      }}
    >
      <Star size={13} fill={starred ? STAR_GOLD : "none"} />
    </button>
  );
}
