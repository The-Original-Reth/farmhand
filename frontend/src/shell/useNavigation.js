import { useEffect, useRef, useState } from "react";
import { Cctv, CircleDollarSign, FolderKanban, Hammer, Layers, Palette, Printer, Settings, Zap } from "lucide-react";

// The menu's sections, in menu order, each at its own address (/models, /printers…); the bare address is Models
export const SECTIONS = [
  { key: "models", label: "Models", Icon: Layers },
  { key: "projects", label: "Projects", Icon: FolderKanban }, // a piece of work: its CAD, STL and 3MF files, printers and parts
  { key: "printers", label: "Printers", Icon: Printer },
  { key: "power", label: "Power", Icon: Zap },
  { key: "farm-cost", label: "Farm cost", Icon: CircleDollarSign }, // filament and electricity, per printer
  { key: "monitor", label: "Monitor", Icon: Cctv },
  { key: "tools", label: "Tools", Icon: Hammer },
  { key: "settings", label: "Settings", Icon: Settings }, // where files are stored, network shares, the settings copy
  { key: "appearance", label: "Appearance", Icon: Palette },
];
const sectionInAddress = () => {
  let key = window.location.pathname.replace(/^\/+|\/+$/g, "");
  if (key === "storage") key = "settings"; // its old address, so bookmarks still open it
  return SECTIONS.some((s) => s.key === key) ? key : "models";
};

const PRINTERS_TOP = [{ label: "Printers" }];
const MODELS_TOP = [{ label: "Models" }];
const PROJECTS_TOP = [{ label: "Projects" }];

// Where the page is: which section, and for Models, Printers and Projects how far in (the breadcrumb's steps: a model,
// a printer, a 3MF on it, a project). Back and Forward move between sections. `onLeave(key)` is called as a menu item is clicked (key: the
// section it opens) and on Back / Forward (no key). A step whose model, printer or 3MF has been deleted takes the section back to its list rather than
// drawing a page for something that no longer exists.
export function useNavigation({ printers, sourceModels, bundles, projects, bundleTitle, onLeave }) {
  const [section, setSection] = useState(sectionInAddress); // one of SECTIONS, as the address says (/printers…)
  const [printerPath, setPrinterPath] = useState(PRINTERS_TOP);
  const [modelPath, setModelPath] = useState(MODELS_TOP);
  const [projectPath, setProjectPath] = useState(PROJECTS_TOP);
  const leave = useRef(onLeave);
  leave.current = onLeave;

  // a section opened from the menu (or by Back / Forward) starts at its top: the list, not a model or printer
  const openSection = (key) => {
    setSection(key);
    if (key === "printers") setPrinterPath(PRINTERS_TOP);
    else if (key === "models") setModelPath(MODELS_TOP);
    else if (key === "projects") setProjectPath(PROJECTS_TOP);
  };
  useEffect(() => {
    const back = () => {
      leave.current();
      openSection(sectionInAddress());
    };
    window.addEventListener("popstate", back);
    return () => window.removeEventListener("popstate", back);
  }, []);

  // A plain click on a menu item: that section here, at its own address
  const goTo = (key) => {
    leave.current(key);
    openSection(key);
    if (window.location.pathname !== `/${key}`) window.history.pushState(null, "", `/${key}`);
  };
  // Straight to one model, printer or project (a project's Open in Models): that page in its own section, with the
  // address following. segment: { modelId } / { printerId } / { projectId }
  const open = (key, segment) => {
    leave.current(key);
    setSection(key);
    if (key === "models") setModelPath([...MODELS_TOP, segment]);
    else if (key === "projects") setProjectPath([...PROJECTS_TOP, segment]);
    else setPrinterPath([...PRINTERS_TOP, segment]);
    if (window.location.pathname !== `/${key}`) window.history.pushState(null, "", `/${key}`);
  };

  const modelPathSafe = modelPath.every((seg) => seg.modelId == null || sourceModels.some((m) => m.id === seg.modelId))
    ? modelPath
    : MODELS_TOP;
  const printerPathSafe = printerPath.every(
    (seg) =>
      (seg.printerId == null || printers.some((p) => p.id === seg.printerId)) &&
      (seg.bundleId == null || bundles.some((b) => b.id === seg.bundleId))
  )
    ? printerPath
    : PRINTERS_TOP;
  const projectPathSafe = projectPath.every((seg) => seg.projectId == null || projects.some((p) => p.id === seg.projectId))
    ? projectPath
    : PROJECTS_TOP;
  useEffect(() => {
    if (modelPathSafe !== modelPath) setModelPath(modelPathSafe);
  }, [modelPathSafe, modelPath]);
  useEffect(() => {
    if (projectPathSafe !== projectPath) setProjectPath(projectPathSafe);
  }, [projectPathSafe, projectPath]);
  useEffect(() => {
    if (printerPathSafe !== printerPath) setPrinterPath(printerPathSafe);
  }, [printerPathSafe, printerPath]);

  const path =
    section === "printers" ? printerPathSafe
      : section === "models" ? modelPathSafe
        : section === "projects" ? projectPathSafe
          : [{ label: SECTIONS.find((s) => s.key === section).label }];
  const setPath =
    section === "printers" ? setPrinterPath : section === "models" ? setModelPath : section === "projects" ? setProjectPath : () => {};
  // the breadcrumb: each step's name (a printer's, a 3MF's, a project's or a model's for the steps into a section)
  const crumbs = () =>
    path.map((seg) => {
      if (seg.label) return seg.label;
      if (section === "printers") {
        if (seg.bundleId) return bundleTitle(bundles.find((b) => b.id === seg.bundleId));
        return printers.find((p) => p.id === seg.printerId).name;
      }
      if (section === "projects") return projects.find((p) => p.id === seg.projectId).name;
      return sourceModels.find((m) => m.id === seg.modelId).name;
    });

  return {
    section,
    goTo,
    open,
    crumbs,
    jumpTo: (i) => setPath(path.slice(0, i + 1)), // a breadcrumb clicked: back up to that step
    printers: { path: printerPathSafe, setPath: setPrinterPath },
    models: { path: modelPathSafe, setPath: setModelPath },
    projects: { path: projectPathSafe, setPath: setProjectPath },
  };
}
