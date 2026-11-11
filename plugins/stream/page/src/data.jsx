import { createContext, useContext, useEffect, useState } from "react";
import { errorText, getFarm } from "./api.js";

// The farm's printers, as Farmhand's useData() gives the Stream page: here from the plugin, which asks Farmhand (and
// shows what it last heard while Farmhand doesn't answer). Asked again every 30 seconds.
const FARM_EVERY_MS = 30000;
const Farm = createContext({ printers: [], farmhandError: null });

export function FarmProvider({ children }) {
  const [farm, setFarm] = useState({ printers: [], farmhandError: null });
  useEffect(() => {
    let live = true;
    const ask = () =>
      getFarm()
        .then((f) => live && setFarm({ printers: f.printers, farmhandError: f.farmhand_error }))
        .catch((e) => live && setFarm((now) => ({ ...now, farmhandError: errorText(e) })));
    ask();
    const timer = setInterval(ask, FARM_EVERY_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);
  return <Farm.Provider value={farm}>{children}</Farm.Provider>;
}

export const useData = () => useContext(Farm);
