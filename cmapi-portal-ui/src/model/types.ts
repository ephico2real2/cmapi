import type { Component } from "./logic.generated";

// The mockup's logic is plain JavaScript, so its empty defaults infer as never[], which no component could read.
// This keeps every type that inference found and opens those. OpenAPI types replace it once the API exists.
type Open<T> = T extends (...args: any[]) => any ? T
  : T extends readonly never[] ? any[]
  : T extends readonly (infer U)[] ? Open<U>[]
  : T extends object ? { [K in keyof T]: Open<T[K]> }
  : T;

/** Everything the portal renders, inferred from the mockup's renderVals(). */
export type Vals = Open<ReturnType<Component["renderVals"]>>;

/** Every tab's props. */
export interface TabProps {
  v: Vals;
}
