# Workshop measurements

Run from `web/portal` with the workshop server already running. These plain Node
tools use `@playwright/test` Chromium, fresh browser contexts, DPR 2, reduced
motion, loaded fonts and a full scroll before returning to the top for capture.

```sh
node workshop/tools/v15-measure.mjs http://localhost:4430 /tmp/measure '/?feed-preview=1&variant=feed-v11&scenario=mixed'
node workshop/tools/census.mjs 'http://localhost:4430/?feed-preview=1&variant=feed-v9&scenario=mixed' /tmp/before.json 1440 900
node workshop/tools/census-diff.mjs /tmp/before.json /tmp/after.json
```

`v15-measure` accepts multiple paths. It writes first-screen/full-page PNGs and
JSON at 1440×900 and 390×844, named from each path's query and viewport. Add
`--card my-card` (repeatable) for sibling card classes beyond `.c15-card`.
`heavyShare` is the area of text ranges at weight ≥500 divided by all displayed
text ranges, including content below the fold. Hidden content is excluded.
`smallText` lists displayed text below 11px; `cardGaps` lists the distinct gaps
between adjacent visible sibling cards; `overflowX` checks document width.
Console errors include browser exceptions and error-level console messages.
For Feed V11, V12 and V13 captures, an optional `state=loading`, `state=empty` or `state=error`
query is a harness instruction: the tool applies the state through the existing
`feed-settings` message used by the parent workshop. Standalone preview URLs
continue to initialize ready; the query alone does not change preview behavior.

`census` records all displayed elements (including below the fold), their DOM
paths, integer CSS-pixel boxes and the fixed computed-style list in the script.
The optional width/height default to 1440/900; use 390/844 for phones.
`census-diff` reports element counts, the total property differences and the
first 20 differences, exiting 1 on differences. Keep viewport and URL identical
between runs. Map-load races can change element counts or properties; repeat
once when a difference is attributable to late map loading, and retain both runs.

The census does not compare SVG fill or stroke, pseudo-elements, opacity,
shadow or outline, same-width digit swaps, or map canvas pixels. It does not
exercise hover, menu or dialog states. Inspect captures and check those
interactions separately. These are local rendering measurements, not live rider
proof.

Climb V16 accepts the same state harness through `climb-settings`. SVG numeral font sizes are measured after the SVG screen transform, so a viewBox-sized 11 CSS-pixel numeral is not mistaken for sub-11 text.
