import { useState } from "react";
import { useBundleExpansion } from "../bundles/versions.jsx";
import { ModelList } from "./ModelList.jsx";
import { ModelPage } from "./ModelPage.jsx";

// The Models page: the list of models, or one model's page (path[1] is { modelId }).
export function ModelsSection({ path, setPath, compareSelection, toggleCompareSelect, sort, onSortChange }) {
  const view = path[1];
  const expansion = useBundleExpansion();
  const [uploadModal, setUploadModal] = useState(null); // null | "stl" | "3mf" | "scan" | "redraw"
  const [query, setQuery] = useState(""); // the search; kept while you open a model and come back

  if (!view) {
    return (
      <ModelList
        query={query} setQuery={setQuery} uploadModal={uploadModal} setUploadModal={setUploadModal}
        sort={sort} onSortChange={onSortChange} setPath={setPath}
      />
    );
  }
  return (
    <ModelPage
      modelId={view.modelId} setPath={setPath} uploadModal={uploadModal} setUploadModal={setUploadModal}
      expansion={expansion} compareSelection={compareSelection} toggleCompareSelect={toggleCompareSelect}
    />
  );
}
