#!/usr/bin/env node
// "Use this size" on a custom recommendation must put the recommended values in the two fields the plan reads.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const main = readFileSync(join(fileURLToPath(new URL("../..", import.meta.url)), "mockups", "portal", "Main.dc.html"), "utf8");
const open = main.indexOf("data-dc-script");
const js = main.slice(main.indexOf(">", open) + 1, main.lastIndexOf("</script>"));
class DCLogic {
  constructor(props) { this.props = props; this.state = {}; }
  setState(update) { this.state = { ...this.state, ...update }; }
}
const Component = new Function("DCLogic", `${js}\n;return Component;`)(DCLogic);

const logic = new Component({ instance: "nonprod", startTab: "quotas" });
logic.setState({ qns: "OCP_GF15/payments-dev" });
const before = logic.renderVals();
assert.match(before.qd.recText, /raise memory to 48 Gi/, "the row recommends 48 Gi");
assert.equal(before.qc.mem, "32", "and has 32 Gi today");
before.qd.useRec();
const after = logic.renderVals();
assert.equal(after.qc.custom, true, "the custom fields open");
assert.equal(after.qc.mem, "48", "with the recommended memory");
after.qPlan();
const planned = logic.renderVals();
assert.equal(planned.qc.nothing, false, "and a plan sees a change");
assert.equal(planned.qc.planned, true);
console.log("ok - a custom recommendation reaches the plan");
