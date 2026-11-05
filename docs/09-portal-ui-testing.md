# How the portal UI was tested

This records how the two portal UIs were tested on 2026-11-04, what was found, and what remains unproven. The method is
the `/test-ui` skill in diagram-kit (`skill/test-ui/SKILL.md`).

There are two UIs and two kinds of proof:

| UI | Must match | Proof |
|---|---|---|
| `mockups/portal/dist/portal.html` (standalone, dc-lite) | The Claude Design render of `Main.dc.html` | DOM and pixels, against the canvas runtime |
| `cmapi-portal-ui/` (React, TypeScript, Vite, PatternFly) | What the mockup says and does | Content and behaviour; PatternFly replaces the look, so never a pixel diff |

Browser: Google Chrome 156.0.8078.80 on macOS, with the windows visible, and Playwright's bundled Chromium.

**Set up first.** In each of `tests/portal/` and `cmapi-portal-ui/`, run `npm install`, then
`npx playwright install chromium`. `PW_CHANNEL=chrome PW_HEADED=1` runs a suite in the installed Chrome. The React test
reads `mockups/portal/dist/portal.html` and needs `npm run build` first.

## Standalone page

**The oracle.** The published Design artifact includes `dc-runtime.js`. Run locally beside a copy of `Main.dc.html`, it
is the real renderer. It is not stored in this repo. The copy of `Main.dc.html` in the artifact was byte-identical to the
repo's (`cmp`).

| Check | Command, in `tests/portal/` | Result |
|---|---|---|
| Logic with no browser | `node logic.test.mjs` | 8 passed |
| Scripted walks, standalone checks | `node interactions.test.mjs` | 180 steps, no console errors |
| Walks compared with the canvas runtime | `--source-dir <folder> --record <file>`, then `--compare <file>` | 180 of 180 steps match on DOM, focus and caret |
| Views compared with the canvas runtime | `node capture.mjs <dir> [<folder>]`, then `node diff.mjs` | 13 of 13 views: 0.000% different, DOM identical |

The 13 views are all nine tabs on nonprod, and Workflow and Quotas on staging and prod, at 1320 px.

The walks cover every scenario on every instance, including "AI agent onboards · rnd" (13 steps, ending in 403); paging
to the end and back; the letter jump; type-ahead, with focus and caret asserted on each key; each filter and sort; picking
a row and planning a change; a team name updating the namespace name; typing mid-field; switching tiers; approving;
rejecting with a required reason; extending and making permanent. The standalone checks cover the hash, the instance
bar, playback, no sideways scroll at 1100, 820 and 390 px on every tab, and running with Google Fonts blocked.

**Not proven: a match with claude.ai itself.** No reference screenshots of the claude.ai render were available, so
the comparison above is with the runtime run locally, not with the Design viewer around it. To finish it, save PNGs
named like the captures (`nonprod-workflow.png`) and run `node diff.mjs <reference-dir> <capture-dir>`.

The original `test-paging.js` and `test-roles.js` could not be found on this machine or in git history.
`logic.test.mjs` covers the same subjects but was written new, not ported.

## React app

| Check | Command, in `cmapi-portal-ui/` | Result |
|---|---|---|
| Generated model is current | `node scripts/extract-model.mjs --check` | Passed |
| App styles use tokens only | `node scripts/check-discipline.mjs` | Passed |
| Types and build | `tsc --noEmit`, `vite build` | Passed |
| Nothing missing from the page | `node tests/parity.test.mjs` | 87 states, 14,088 strings, 0 missing |
| Nothing invented by the page | The same test | 0 added |
| Layout at 1440, 820 and 390 px, all tabs | The same test | No sideways scroll, no leftover placeholders |
| Accessibility, axe at 1440 and 390 px | The same test | No serious or critical findings |

The test drives the mockup and the page through the same steps and compares after each: all tabs on all instances,
every nonprod scenario to its end, then Quotas, New namespace, Approvals and Expiration actions.

The check was seen to fail: changing the heading "Why it needs approval" made the test report it as missing in 6 states
and report the new heading as added. The change was reverted and confirmed with a grep.

**Not proven.** No API exists, so there are no contract tests, loading states or error states, and no sign-in to test.
See `cmapi-portal-ui/MOCKUP-CONTRACT.md`. Keyboard use relies on PatternFly and axe; no walk tabs through every
control. No CI runs these suites yet.

## What testing found

| Found by | Problem | Fix |
|---|---|---|
| Identical DOM with different pixels | The artboard sat at y = 32.1875 because the bar's height was fractional, moving up to 1.4% of pixels | A whole-pixel bar height |
| Step-by-step comparison | React mirrors a textarea's value into its text child | The runtime does too |
| Reading the source in full | An invented Workflow intro, a "Share" column and placement headings | Replaced with the file's content |
| Reverse content check, added after that | A check for missing strings cannot see invented ones | The test now fails on both |
| Layout run at 820 px | PatternFly's overflow mode folded a tab into a menu | Scrolling tabs |
| Axe | A long token made a KPI card a scrollable region no keyboard could reach | Text wraps inside cards |
| Installed Chrome | `/favicon.ico` 404 reported as a console error; a dev server hid it | An inline icon |

Mockup behaviour worth a decision, left unchanged in `Main.dc.html`: the Team DL field has a value and no handler, so
typing in it does nothing. The React app makes it editable.
