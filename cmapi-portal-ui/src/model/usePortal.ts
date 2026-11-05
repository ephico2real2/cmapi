import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { Component, PROPS } from "./logic.generated";
import type { Vals } from "./types";

const FIELDS = { instance: PROPS.instance, startTab: PROPS.startTab };

function fromHash() {
  const [instance, startTab] = location.hash.slice(1).split("/");
  const pick = (meta: { options: string[]; default: string }, wanted: string) => (meta.options.includes(wanted) ? wanted : meta.default);
  return { instance: pick(FIELDS.instance, instance), startTab: pick(FIELDS.startTab, startTab) };
}

const current = (logic: Component) => ({ instance: logic.state.inst as string, startTab: (logic.state.tab || logic.props.startTab) as string });

/**
 * The portal's one source of state: the mockup's logic class, standing in for the API until it exists.
 * The hash holds the instance and tab. It follows the portal's own controls, and a changed hash reopens the portal.
 * `session` changes with each reopening: keyed on it, fields the logic does not hold (Justification, Team DL) start over too.
 */
export function usePortal(): { v: Vals; session: number } {
  const [{ logic, session }, setPortal] = useState(() => ({ logic: new Component(fromHash()), session: 0 }));
  const subscribe = useCallback((listener: () => void) => logic.subscribe(listener), [logic]);
  useSyncExternalStore(subscribe, () => logic.state);

  const { instance, startTab } = current(logic);
  useEffect(() => {
    const hash = `#${instance}/${startTab}`;
    if (location.hash !== hash) history.replaceState(null, "", hash);
  }, [instance, startTab]);

  useEffect(() => {
    const onHash = () => {
      const wanted = fromHash();
      const now = current(logic);
      if (wanted.instance !== now.instance || wanted.startTab !== now.startTab) {
        const reopened = new Component(wanted);
        setPortal((was) => ({ logic: reopened, session: was.session + 1 }));
      } else {
        // The same view under another hash, such as a bad one on the defaults: no render will correct it, so do it here.
        history.replaceState(null, "", `#${now.instance}/${now.startTab}`);
      }
    };
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, [logic]);

  // Playback runs on a timer the logic owns.
  useEffect(() => () => logic.componentWillUnmount(), [logic]);

  return { v: logic.renderVals() as unknown as Vals, session };
}
