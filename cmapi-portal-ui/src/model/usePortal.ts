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
 */
export function usePortal(): Vals {
  const [logic, setLogic] = useState(() => new Component(fromHash()));
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
      if (wanted.instance !== now.instance || wanted.startTab !== now.startTab) setLogic(new Component(wanted));
    };
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, [logic]);

  // Playback runs on a timer the logic owns.
  useEffect(() => () => logic.componentWillUnmount(), [logic]);

  return logic.renderVals() as unknown as Vals;
}
