import { PrinterList } from "./PrinterList.jsx";
import { PrinterPage } from "./PrinterPage.jsx";

// The Printers page: the list of printers, or one printer's own page
export function PrintersSection({ path, setPath, compareSelection, toggleCompareSelect }) {
  const view = path[1]; // {printerId}
  return view ? (
    <PrinterPage printerId={view.printerId} compareSelection={compareSelection} toggleCompareSelect={toggleCompareSelect} />
  ) : (
    <PrinterList setPath={setPath} />
  );
}
