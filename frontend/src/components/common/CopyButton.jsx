import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { fs, ui } from "../../theme.js";
import { errorText } from "../../api.js";
import { toolButton } from "../../styles.js";

// Copying text for the operator: `copy(text)` puts it on the clipboard and `copied` is true for a moment after; `error`
// says why it couldn't be (the browser only allows it on https or this computer's own address). Each place shows the
// error where it fits.
export function useCopy() {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState(null);
  const copy = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (e) {
      setError(`Couldn't copy it (${errorText(e)}): select it and copy it by hand.`);
    }
  };
  return { copied, error, copy };
}

// The Copy button, saying "Copied" for a moment after: `copying` is a useCopy(), `text` what it copies
export function CopyButton({ copying, text, testId }) {
  return (
    <button type="button" data-testid={testId} onClick={() => copying.copy(text)} style={{ ...toolButton(12), ...ui, fontSize: fs(12) }}>
      {copying.copied ? <Check size={13} /> : <Copy size={13} />} {copying.copied ? "Copied" : "Copy"}
    </button>
  );
}
