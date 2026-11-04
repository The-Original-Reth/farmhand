import { useEffect, useRef, useState } from "react";
import { errorText, getConfig, saveConfig, saveConfigOnExit } from "../api.js";
import { applyAppearance, loadAppearance, normalizeAppearance, saveAppearance } from "../appearance.js";
import { thisMonth, withNewAverage } from "../lib/energyPrice.js";
import { readStored, writeStored } from "../lib/storage.js";
import { loadModelSort, normalizeModelSort, saveModelSort } from "../models/modelSort.js";

const PENDING_CONFIG_KEY = "farmhand.configPending"; // changes not yet confirmed by the server
const NO_ENERGY_PRICES = { current: null, history: [], months: {} };

// Two config patches as one, the later winning. Each preference is saved on its own on the server, so two changed
// close together are both kept.
const mergePatches = (a, b) => {
  const merged = { ...a, ...b };
  if (a.preferences && b.preferences) merged.preferences = { ...a.preferences, ...b.preferences };
  return merged;
};

// Changes the server hasn't confirmed yet are also written down in this browser. If the page is closed, or the
// server is unreachable, they're sent on the next visit instead of being overwritten by the server's older copy.
const rememberPending = (patch) => writeStored(PENDING_CONFIG_KEY, patch && Object.keys(patch).length ? patch : null);

// this browser's time zone ("Europe/Amsterdam"), or null if it can't say
const browserTimeZone = () => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
};

const listOr = (v) => (Array.isArray(v) ? v : []);

// The electricity prices kept in the server's preferences: { current, history, months } (see lib/energyPrice.js)
const energyPricesOf = (prefs) => ({
  current: typeof prefs.energy_price_per_kwh === "number" ? prefs.energy_price_per_kwh : null,
  history: listOr(prefs.energy_price_history),
  months: prefs.energy_price_months && typeof prefs.energy_price_months === "object" ? prefs.energy_price_months : {},
});

const sameLook = (a, b) =>
  a.scheme === b.scheme && a.contrast === b.contrast && a.font === b.font && a.size === b.size && a.file_name_color === b.file_name_color;

// The settings the server keeps for every browser: the look, the models' sort order, Monitor's layout and zoom, the
// Tools page's links and the price of electricity. Each change shows at once and is sent to the server; most wait a
// moment so a slider dragged through many values is sent once (queueSave). The server also copies them to the
// network folder chosen in Settings.
//
// Appearance (colour scheme, text brightness, font and size) is applied while this hook runs, so it must be used in
// the component that draws everything: components read the live theme (theme.js) as they render. What this browser
// remembers of it is only used to paint the right look at once, before the server has answered.
export function useSavedSettings() {
  const [appearance, setAppearance] = useState(loadAppearance); // the SAVED look
  const [preview, setPreview] = useState(null); // a look being tried on the Appearance page, not saved yet (null = none)
  const [modelSort, setModelSort] = useState(loadModelSort);
  const [monitorOrder, setMonitorOrder] = useState([]); // the Monitor page's cameras as dragged into order
  const [monitorMaxZoom, setMonitorMaxZoom] = useState(4); // how far in a Monitor camera can be zoomed
  const [toolLinks, setToolLinks] = useState([]); // the Tools page's websites
  const [energyPrices, setEnergyPrices] = useState(NO_ENERGY_PRICES); // the price of electricity set on the Power page
  const [saveState, setSaveState] = useState({ phase: "idle" }); // idle | saving | saved | error
  const pendingSave = useRef({});
  const saveTimer = useRef(null);
  applyAppearance(preview || appearance); // a preview shows live; it only becomes the saved look when Save is pressed

  const adoptServerConfig = (config) => {
    const prefs = config.preferences || {};
    const a = normalizeAppearance(config.appearance);
    const sort = normalizeModelSort(prefs.model_sort);
    setAppearance(a);
    saveAppearance(a);
    setModelSort(sort);
    saveModelSort(sort);
    setMonitorOrder(listOr(prefs.monitor_order));
    setMonitorMaxZoom(prefs.monitor_max_zoom || 4);
    setToolLinks(listOr(prefs.tool_links));
    // The server saves each month's Farm cost record when the month ends in the farm's time zone: tell it this
    // browser's, when it doesn't know it yet or it's moved
    const zone = browserTimeZone();
    if (zone && prefs.time_zone !== zone) queueSave({ preferences: { time_zone: zone } });
    setEnergyPrices(energyPricesOf(prefs));
  };
  const loadServerConfig = () =>
    getConfig()
      .then(({ config }) => adoptServerConfig(config))
      .catch(() => {
        /* the server isn't answering: carry on with what this browser remembers */
      });
  useEffect(() => {
    const pending = readStored(PENDING_CONFIG_KEY);
    if (pending && Object.keys(pending).length) {
      // changes made here that never reached the server: send them first, then show what the server now holds
      saveConfig(pending)
        .then((r) => {
          rememberPending(null);
          adoptServerConfig(r.config);
        })
        .catch(() => {
          /* still can't reach it: keep them for next time and carry on with what this browser remembers */
        });
    } else {
      loadServerConfig();
    }
    // closing or leaving the page within the short wait below must not lose the last change
    const onHide = () => {
      if (Object.keys(pendingSave.current).length) saveConfigOnExit(pendingSave.current);
    };
    window.addEventListener("pagehide", onHide);
    return () => window.removeEventListener("pagehide", onHide);
  }, []);

  const flushSave = async () => {
    const patch = pendingSave.current;
    pendingSave.current = {};
    try {
      const result = await saveConfig(patch);
      rememberPending(pendingSave.current); // anything changed while that was in flight is still waiting
      setSaveState({ phase: "saved", mirror: result.mirror });
    } catch (e) {
      pendingSave.current = mergePatches(patch, pendingSave.current); // not delivered: keep it, newer values winning
      rememberPending(pendingSave.current);
      setSaveState({ phase: "error", message: errorText(e) });
    }
  };
  // A slider drags through many values: wait for it to settle rather than rewriting the network file for each
  const queueSave = (patch, { immediate = false } = {}) => {
    pendingSave.current = mergePatches(pendingSave.current, patch);
    rememberPending(pendingSave.current);
    setSaveState({ phase: "saving" });
    clearTimeout(saveTimer.current);
    if (immediate) flushSave();
    else saveTimer.current = setTimeout(flushSave, 400);
  };

  // Appearance: changes are a live PREVIEW until Save is pressed. Leaving the page without saving undoes them.
  const changeAppearance = (next) => setPreview(sameLook(next, appearance) ? null : next);
  const discardAppearance = () => setPreview(null);
  const commitAppearance = () => {
    if (!preview) return;
    const next = preview;
    setAppearance(next);
    saveAppearance(next);
    setPreview(null);
    queueSave({ appearance: next }, { immediate: true });
  };
  const changeModelSort = (next) => {
    setModelSort(next);
    saveModelSort(next);
    queueSave({ preferences: { model_sort: next } });
  };
  // The Monitor page's Save layout: sent at once, and only taken as saved once the server says so (an error is shown
  // there, by the button)
  const saveMonitorOrder = async (next) => {
    const r = await saveConfig({ preferences: { monitor_order: next } });
    setMonitorOrder(r.config.preferences.monitor_order);
  };
  // The Tools page's Save, the same way: an error is shown there
  const saveToolLinks = async (next) => {
    const r = await saveConfig({ preferences: { tool_links: next } });
    setToolLinks(r.config.preferences.tool_links);
  };
  const changeMonitorMaxZoom = (next) => {
    setMonitorMaxZoom(next);
    queueSave({ preferences: { monitor_max_zoom: next } });
  };
  // The average cost: counts from this month on (earlier months keep theirs; the server applies the same rule)
  const changeEnergyPrice = (next) => {
    const month = thisMonth();
    setEnergyPrices((now) => withNewAverage(now, next, month));
    queueSave({ preferences: { energy_price_per_kwh: next, energy_price_from: month } });
  };
  // One month's own price, typed in its row on the Power page; null = back to the average cost that counted then
  const changeMonthPrice = (month, price) => {
    const months = { ...energyPrices.months };
    if (price == null) delete months[month];
    else months[month] = price;
    setEnergyPrices((now) => ({ ...now, months }));
    queueSave({ preferences: { energy_price_months: months } });
  };

  return {
    saveState,
    loadServerConfig,
    appearance: { saved: appearance, shown: preview || appearance, change: changeAppearance, save: commitAppearance, discard: discardAppearance },
    modelSort: { value: modelSort, change: changeModelSort },
    monitor: { order: monitorOrder, saveOrder: saveMonitorOrder, maxZoom: monitorMaxZoom, changeMaxZoom: changeMonitorMaxZoom },
    tools: { links: toolLinks, save: saveToolLinks },
    energy: { prices: energyPrices, changePrice: changeEnergyPrice, changeMonthPrice },
  };
}
