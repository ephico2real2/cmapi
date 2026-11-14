import "@patternfly/react-core/dist/styles/base.css";
import "./app.css";
import { StrictMode } from "react";
import type { ComponentType } from "react";
import { createRoot } from "react-dom/client";

// Two builds from one source. `vite build` is the portal on the API. `vite build --mode demo` is the mockup's stand-in,
// which runs the mockup's sample logic. The mode is a constant at build time, so the portal's bundle leaves out the
// sample logic and its data: tests/api/bundle.test.mjs holds that.
const app: Promise<ComponentType> = import.meta.env.MODE === "demo"
  ? import("./App").then((m) => m.App)
  : import("./portal/PortalApp").then((m) => m.PortalApp);

void app.then((App) => createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>));
