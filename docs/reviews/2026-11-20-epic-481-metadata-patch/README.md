# Epic #481: change the metadata of existing namespaces (spike #482)

| File | What it is |
|---|---|
| [`design.md`](design.md) | The final design for build: the coordinator (Opus 5.5) on Codex's base, with the owner's decisions of 2026-11-20 |
| [`codex-base-design.md`](codex-base-design.md) | Codex `gpt-6.2-astra`'s base design (high), unchanged |
| [`second-pass.md`](second-pass.md) | The coordinator's second pass: what was kept, ruled out or simplified, and why |
| [`mockup-namespaces-tab.html`](mockup-namespaces-tab.html) | The Namespaces tab mockup (open it in a browser). Published privately for the owner as a claude.ai artifact |

The owner's decisions, 2026-11-20:
- The tab is called **Namespaces**.
- Git is the store. One open request per namespace (409) and `If-Match` (412) keep two people from changing one namespace at once.
- The tab shows the cluster's live state beside Git, with drift highlighted.
- Discovery happens after the cluster is chosen: lookup as you type, mnemonic chips and a mnemonic filter.
- No permission filter on discovery for now ("we do not enforce that with Keycloak presently"). The PATCH still checks the caller's permission.
- Complexity is fine only where it is the only way to keep a guarantee. So the per-key choice after a 412 applies only to keys that both sides changed.

Stories: #483 (contract), #484 (Namespaces tab), #485 (Swagger and ReDoc). They start after #479 Phase 1 (PR #488) merges.
The configuration rollout window found here is cross-cutting and is #486.
