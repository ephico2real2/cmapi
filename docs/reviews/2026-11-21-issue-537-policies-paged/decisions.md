# Issue #537: the Policies tab in sections, with Results by policy last and paged

The owner decided the layout in #537 (2026-11-21, after OB1 run 31's live screenshot of 1440 x 5662 px): the header pill;
Clusters, the failing resources and the refusals, each collapsible and open; Results by policy last, collapsible and closed,
25 rows a page with `‹ 1 2 3 … N ›`, 25, 50 or 100 a page, and "1–25 of 80". Each section header shows its count; the
cluster filter stays with Results by policy; a new filter or page size starts again at page 1. This page records how it was
built and why, from the sources fetched on 2026-11-21. It does not reopen the layout.

## Sources, fetched 2026-11-21

| Source | What it says | Used for |
|---|---|---|
| PatternFly 6.7.0, Card, https://www.patternfly.org/components/card/ | "A card can be made expandable using the `isExpanded` property." "In the collapsed state, only the card header is shown." "Place any content that you want to be hidden within the `<CardExpandableContent>` component." | Each section is the tab's existing `Card`, made expandable (`Section` in `src/components/ui.tsx`) |
| PatternFly 6.7.0, Card accessibility, https://www.patternfly.org/components/card/accessibility | `toggleButtonProps`: "Sets props on the card's toggle. **Required** when a card is expandable." "The `aria-labelledby` should include the `id` of a `CardTitle` sub-component if one exists." "The `aria-expanded` property must be set as the card's current expanded state." | The toggle gets `aria-expanded` and an `aria-labelledby` of the title and the count |
| PatternFly 6.7.0, Pagination, https://www.patternfly.org/components/pagination/ | `perPageOptions` default "[ { title: '10', value: 10 }, { title: '20', value: 20 }, { title: '50', value: 50 }, { title: '100', value: 100 } ]"; its navigation is "navigate to first page", previous, "user inputs page number", next and last | PatternFly's Pagination has no numbered page buttons, so it cannot show `‹ 1 2 3 … N ›` |
| PatternFly 6.7.0, Pagination design guidelines, https://www.patternfly.org/components/pagination/design-guidelines | The per-page selector is "Used to choose the number of items displayed on a single page at once"; top pagination is "Placed above the component it controls" | The pager sits above the table, as the tab's other pager does |
| `@patternfly/react-core` 6.7.0, `dist/esm/components/Pagination/index.d.ts` (installed) | exports `./Pagination` and `./ToggleTemplate` only | `PaginationOptionsMenu` is not exported, so the per-page choice is the Per page chips that the Quotas tab already uses for 25, 50 and 100 |
| MDN, aria-current, https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Reference/Attributes/aria-current | `page`: "Represents the current page within a set of pages"; "Only mark one element in a set of elements as current with `aria-current`." | The page shown has `aria-current="page"`, and only that one |
| React, "You Might Not Need an Effect", https://react.dev/learn/you-might-not-need-an-effect | "Always check whether you can reset all state with a key or calculate everything during rendering instead." Its example: "✅ Best: Calculate everything during rendering", `const selection = items.find(item => item.id === selectedId) ?? null;` | The page is stored with the cluster it was chosen for, and read as page 1 for any other cluster: computed while rendering, with no Effect |
| U.S. Web Design System, Pagination, https://designsystem.digital.gov/components/pagination/ | "a maximum of seven slots"; "The first slot is always the first page of the set"; the last page of a bounded set is always a link; wrap it in a `<nav>` with "a unique, descriptive ARIA label"; `aria-current="page"` on the current page; `aria-label="page [#]"` on each page link | `pageSlots()`: every page up to 7, then 1, the current page's neighbours, the last page and a gap; `nav aria-label="Results by policy pages"`; each page button is named "Page N" |

PatternFly has no numbered-pages component, so the pager is built from its parts (`Button`, `ToggleGroup`, `Flex`) with the
USWDS slot rule and the ARIA above. This is the only way to show the owner's `‹ 1 2 3 … N ›` on PatternFly 6.7.

## Decisions

| Question | Decision | Why |
|---|---|---|
| Expandable Card or ExpandableSection | Expandable `Card` | The tab's sections are Cards already; PatternFly's expandable Card keeps the title and adds a toggle, and renders nothing of the body while closed |
| Where the count goes | A `Badge` beside the `h2`, outside it; the toggle's name is the title and the count | The heading stays the section's name (the existing checks find a section by it, some exactly); a screen reader hears "Results by policy 80" on the toggle |
| Rows-per-page control | The Per page chips (25, 50, 100) of the Quotas tab | PatternFly does not export its per-page menu; the chips show the three choices the owner named, and the portal already uses them |
| Prev and next | `‹` and `›` buttons named "Previous page" and "Next page", `aria-disabled` at either end | As the tab's other pager, which keeps a disabled button focusable (`isAriaDisabled`) |
| Where the page and the page size live | Component state, not the address | The API returns every policy at once (`GET /api/v1/policies/results`, `policies`), so the page is the browser's; as the cursors, they belong to one view |
| Reset to page 1 | The page is stored with the cluster it belongs to; a different cluster, from a chip or from the address, reads as page 1; a new page size sets page 1 | React, "You Might Not Need an Effect" (above): computed while rendering, so no Effect resets it a render late |
| A link to a chosen policy (`#policies?policy=…`) | Results by policy still starts closed | The owner: closed by default. The chosen policy is named in the failing resources' heading and in the address |
| The mockup's sample policies | 14 rendered checks for each environment, beside the 9 hand-written ones (36 on nonprod and staging, 23 on prod) | With 8 policies the mockup could not show a second page; the names follow the bundle's (`cmapi-<family>-<env>-<kind>-<key>-<rule>`) |
