// The shared palette for the workshop finals: one file, 34 colours.
// Designed 2026-10-01 against standardreserve.xyz (33 colours across its rooms); the five finals rendered 280.
// The workshop's Palette toggle previews any room on these tokens; every other colour maps to its nearest token for its role.
export type PaletteRole = 'surface' | 'text' | 'line' | 'svg' | 'shadow';
export type PaletteToken = { name: string; value: string; roles: PaletteRole[]; note: string };

export const PALETTE: PaletteToken[] = [
  // Grounds and rules: one warm-green neutral ramp, lightest to darkest.
  { name: 'card', value: '#ffffff', roles: ['surface', 'text', 'line', 'svg', 'shadow'], note: 'Neutral step 0 (L100). Cards and plates on paper; type on olive and blue fills; white marker rings.' },
  { name: 'raised', value: '#fafbf7', roles: ['surface', 'svg'], note: 'L98.4. Floating map panels and controls; chart wells set into a card.' },
  { name: 'paper', value: '#f5f5f0', roles: ['surface', 'line', 'svg', 'text'], note: 'L96.4, the warmest step (hue 110). The one page ground for all five rooms; quiet plates on cards (support band, effort strips); the ring around the profile portrait.' },
  { name: 'inset', value: '#edf0e7', roles: ['surface', 'line', 'svg'], note: 'L94.4, sage-tinted. Wells and plates set into a card (chart side wells, table heads, vault bands), selected rows, segmented tracks, the phone tab strip, quiet in-card dividers, chart grid lines.' },
  { name: 'plate', value: '#e6e9e0', roles: ['surface', 'line', 'svg'], note: 'L91.9. Object header plates (Example Rider bar, Vault head), map frames; the default hairline on white.' },
  { name: 'rule', value: '#dee2d7', roles: ['line', 'surface', 'svg', 'text'], note: 'L89.3. Hairlines on paper; rules on tinted plates, pressed chips; map-control borders and dividers in every room; the climb window in the feed\'s elevation strip is its olive-500 wash.' },
  { name: 'rule-strong', value: '#c9cec0', roles: ['line', 'surface', 'svg', 'text'], note: 'L82. Input borders, vault bars, empty calendar days; the climb room\'s elevation silhouette (kept heavier than authored so the hill holds its weight).' },
  // Ink: five steps set by contrast. ink-3 is the lightest that holds 4.5:1 on every light surface; ink-4 holds 4.3:1 on white.
  { name: 'ink-5', value: '#89937e', roles: ['text', 'svg', 'line'], note: 'L59.5, C12.5: where the faint authored labels sit (L58-61), keeping some of their sage. Faint: absent-value dashes, footer credits, faint units and tags, the map scale bar, the ride elevation relief (at its own alpha). 3.2:1 on white: never a control.' },
  { name: 'ink-4', value: '#747c69', roles: ['text', 'svg', 'line'], note: 'L51. Tertiary: dates, units, labels, captions, axis ticks, row chevrons; the elevation edge and analysis elevation channel. 4.35:1 on white, 3.8:1 on inset.' },
  { name: 'ink-3', value: '#636b5c', roles: ['text', 'svg', 'line', 'surface', 'shadow'], note: 'L44, C9.6 at hue 130, the hue the authored labels share: between the ride\'s sage labels (C13) and the profile\'s grey ones (C5). Secondary labels, nav items, comment text, icons. At least 4.5:1 on every light surface down to plate.' },
  { name: 'ink-2', value: '#4b4f45', roles: ['text', 'svg', 'line', 'surface'], note: 'L33. Strong secondary: section heads, bios, definitions, map attributions in every room; the neutral Follow button. 8.4:1.' },
  { name: 'ink', value: '#292c27', roles: ['text', 'svg'], note: 'L17.5. Primary type, titles and figures (unchanged). 14:1 on white.' },
  // The header band and the olive family, matched in lightness to the inks.
  { name: 'band', value: '#20251c', roles: ['surface', 'line', 'shadow'], note: 'L13.9. The near-black olive header band in every room (olive-900 end of the green ramp); tint for soft shadows.' },
  { name: 'band-raised', value: '#383e2f', roles: ['surface', 'line'], note: 'L25, one quiet olive step above the band (authored value): the selected nav pill under bone type, the band\'s bottom seam. Not the primary-action olive-800.' },
  { name: 'bone', value: '#f8f6ea', roles: ['text', 'svg'], note: 'Warm type on the band and on band-raised: the wordmark, the selected nav label, the avatar glyph on the band in every room. The one cream in the chrome.' },
  { name: 'band-muted', value: '#b6bcab', roles: ['text'], note: 'Muted type on the band: inactive nav in every room (the profile\'s by selector), the page label. 8:1 on band, a clear step under bone.' },
  { name: 'olive-800', value: '#384630', roles: ['surface', 'text', 'svg', 'line', 'shadow'], note: 'Primary action fill (Collect DUNG, unchanged), dark avatars (the band avatar disc in every room) and the ride object-bar avatar initials beside the olive-800 name; the hero time on the climb-result plate, the PB card rank. White on it is 10:1.' },
  { name: 'olive-700', value: '#435934', roles: ['text', 'svg', 'line', 'surface'], note: 'L35, C25: olive figures and strong links (Open climb), tab underline, feed comment names and the card avatar initials beside them. Near ink-2 in lightness, with enough chroma that the action still reads green; 7.7:1 on white.' },
  { name: 'olive-600', value: '#576a45', roles: ['text', 'svg', 'line', 'surface'], note: 'Mid olive, a touch under olive-700\'s chroma: resting olive links and controls (Analyze ride, rail links, map tools and their labels), the feed climb row time and Ride CAL figure, the climb room\'s light-avatar initials. Same lightness as ink-3.' },
  { name: 'olive-500', value: '#70805a', roles: ['surface', 'svg', 'line', 'shadow'], note: 'Accent: focus ring, calendar ride dots, start marker, climb glyphs and map climb traces, the PR tag, the feed strip\'s climb window (at its own alpha); by assignment, the sage captions on the feed\'s two climb plates (result plate: rank, gain, footer; network climb card: kicker, result, glyph; 3.5-3.7:1) and the climb room\'s resting Compare and sort controls (4.3:1 on white). Marks, plate captions and quiet controls, not body text.' },
  { name: 'sage-300', value: '#a4b390', roles: ['surface', 'svg', 'line'], note: 'Data fills: rhythm and activity bars, the feed network map\'s activity dots (opaque), chart halos and quiet chart strokes.' },
  { name: 'sage-100', value: '#d2dcc3', roles: ['surface', 'svg', 'line'], note: 'Pale sage: zero bars and rest-day ticks, collect plate, green-tinted rules; the climb PB card\'s avatar disc, a sage chip that parts from the plate head it sits on.' },
  // Route: the ride, and the climbs on it.
  { name: 'route', value: '#456ca0', roles: ['text', 'svg', 'line'], note: 'Route line, map profile line, route text (unchanged); the ride map\'s numbered climb pins, as soft as the line they label (white numerals 5.4:1).' },
  { name: 'route-strong', value: '#225aad', roles: ['surface', 'svg', 'line', 'text', 'shadow'], note: 'Climbs on the route: map climb segments (existing value), focused climb; also the analysis speed channel.' },
  // Data channels.
  { name: 'chart-power', value: '#613393', roles: ['svg', 'text', 'line', 'surface'], note: 'Power trace, bars and values (unchanged).' },
  { name: 'chart-power-ink', value: '#544065', roles: ['text'], note: 'Power figures in readouts (unchanged).' },
  { name: 'chart-power-soft', value: '#7f669b', roles: ['svg', 'line', 'shadow'], note: 'Power distribution bins, power focus (unchanged).' },
  { name: 'chart-power-wash', value: '#d8cee1', roles: ['surface', 'svg', 'line'], note: 'Pale end of power density legends and selections.' },
  { name: 'chart-heart', value: '#c22032', roles: ['svg', 'text', 'surface'], note: 'Heart-rate channel. The only red outside the rank-mark images.' },
  { name: 'chart-cadence', value: '#007a61', roles: ['svg', 'text', 'surface'], note: 'Cadence channel.' },
  { name: 'chart-compare', value: '#5c8a9c', roles: ['svg', 'line', 'surface', 'text'], note: 'Slate companion: the comparison effort in climb history. Marks, not body copy.' },
  // Used sparingly.
  { name: 'gold', value: '#c8b573', roles: ['shadow', 'line', 'svg', 'surface'], note: 'Rationed: the 3px active-nav rule; the current-effort bar.' },
  { name: 'gold-ink', value: '#85631f', roles: ['text', 'svg'], note: 'New-best text; also the analysis grade channel.' },
  { name: 'status-error', value: '#91513d', roles: ['text', 'svg', 'line'], note: 'Brick error and validation text, 6.1:1 on white. Distinct from heart-rate red.' },
];

// Where the nearest token carries the wrong meaning, a legacy colour is assigned by hand,
// for every role or per role. Keys are the authored colour as #rrggbb. A colour set through a
// custom property whose name gives no role (e.g. --c10-support) is only reached by a string entry.
export const LEGACY: Record<string, string | Partial<Record<PaletteRole, string>>> = {
  // Route.
  '#3668ab': { surface: 'route' }, // ride map climb pins: as soft as the line they label
  // Grounds: plates set into a card stay a half-step under the page, never the page itself.
  '#f0f1ed': 'inset', // ride chart side wells, climb support plates and segmented track (--c10-support)
  '#eff0eb': { line: 'inset' }, // ride summary column divider
  '#e9ece1': { surface: 'inset' }, // ride phone tab strip, one step above the rider plate
  '#f1f3ed': { surface: 'raised' }, // feed elevation-strip frame (the relief inside it is paper), so it parts from the plates below
  '#eeefe9': { surface: 'inset', text: 'bone' }, // profile plates on the paper ground; profile band type
  '#dfe2db': { line: 'rule' }, // profile hairlines on the paper ground
  '#f7f7f3': { shadow: 'paper' }, // profile portrait ring: the outer stroke matches the ring
  '#dce2d3': { surface: 'sage-100', line: 'rule' }, // light avatar discs on tinted heads; the feed rail avatar is a rule disc by selector; the map search divider stays a rule
  '#d9e0cf': { surface: 'sage-100' }, // rhythm rest-day ticks
  '#d4d6cf': { svg: 'rule-strong' }, // climb elevation silhouette keeps its weight
  '#dfe6d3': { line: 'rule' }, // climb history card outline at its footer plate: one rule all the way round
  '#91a77c': { svg: 'olive-500' }, // feed elevation-strip climb window (at its own alpha): parts from the strip ground as authored
  // Chrome.
  '#383e2f': { surface: 'band-raised' }, // selected nav pill
  '#3e4233': { line: 'band-raised' }, // seam under the header band
  '#e3e7d9': { text: 'bone' }, // avatar glyph on the band
  '#394332': { surface: 'olive-800' }, '#d8e2cb': { text: 'bone' }, // the climb shell's band avatar, matching the feed's
  '#68735d': 'ink-3', // ride more-nav ellipsis, matching the nav items beside it
  '#f6f5ed': { text: 'bone' },
  '#f8f6ea': 'bone',
  '#f5f5e9': 'bone',
  // Type.
  '#293a2d': { text: 'ink' }, // map climb title
  '#515b46': { text: 'ink-2' }, // ride 'Climbs on this ride' head
  '#535f49': { text: 'ink-2' }, // feed rail and network heads
  '#73806a': { text: 'ink-3' }, // feed comment body: content, not caption
  '#525e47': { text: 'olive-700' }, // feed comment names, matching their avatar initials and a clear step over the ink-3 body (rail heads take ink-2 by selector)
  '#526047': { text: 'ink-2' }, // map attribution: neutral, not the action olive (ink-3 falls under 4.5:1 on the tiles)
  '#596250': { text: 'ink-2' }, // feed map attribution, matching the map room
  '#7b8b6e': 'ink-4', // map selected-card close X: a control, matching the sheet chevron
  '#8b9681': { text: 'ink-4' }, // map results-head count
  '#8d9681': 'ink-4', // climb row arrows, matching the other chevrons
  '#849373': 'ink-4', // climb PB-time arrow, matching the Local Legend arrow in the same rail
  '#9da68c': { line: 'ink-5' }, // map scale-bar outline: a neutral instrument, not a data fill
  '#a8b09e': { text: 'ink-5' }, // climb absent-value dashes
  '#a0a794': { text: 'ink-5' },
  // Contrast holds: authored greys that sit just past the midpoint between two ink steps
  // round to the darker step, so no label loses legibility.
  '#7e8873': { text: 'ink-4' }, '#7e8875': { text: 'ink-4' }, '#7e8975': { text: 'ink-4' },
  '#858b7d': { text: 'ink-4' }, '#7f8876': { text: 'ink-4' },
  '#858c7a': { text: 'ink-4' },
  '#67745a': { text: 'ink-3' }, '#6d765f': { text: 'ink-3' }, '#68725e': { text: 'ink-3' }, '#6e795f': { text: 'ink-3' },
  '#6e7864': { text: 'ink-3' }, '#6e7763': { text: 'ink-3' }, '#65735b': { text: 'ink-3' }, '#69775d': { text: 'ink-3' },
  '#697361': { text: 'ink-3' }, '#71776b': { text: 'ink-3' }, '#69765e': { text: 'ink-3' },
  '#68735c': { text: 'ink-3' }, '#73776e': { text: 'ink-3' }, '#71776a': { text: 'ink-3' },
  // Olive meaning.
  '#3d5030': { text: 'olive-800' }, // feed climb-result hero time
  '#475439': { text: 'olive-800' }, // ride object-bar avatar initials, matching the rider name beside them
  '#718360': { text: 'olive-500' }, // feed climb-result captions
  '#758665': 'olive-500', // feed climb-result footer ('All 3 climbs', 'Ride CAL') and its chevrons
  '#7e8e6a': { text: 'olive-500' }, // climb 'Compare': a resting control, kept olive
  '#707c60': { text: 'olive-500' }, // climb 'Recent' sort
  '#6b795e': { text: 'olive-600' }, // climb 'Expand map' label, matching its glyphs
  '#46533b': { text: 'olive-800' }, // climb PB card rank, matching the hero time (phone already lands there)
  '#738861': { text: 'olive-500' }, // feed '5s faster' gain, matching the plate's other sage captions
  '#7e8c70': { text: 'olive-500' }, '#7e8d70': { text: 'olive-500' }, '#859776': 'olive-500', // feed network climb card: kicker, result caption, glyph, as on the result plate beside it
  '#68785a': { text: 'olive-600' }, // feed climb row time
  '#758b5d': 'olive-500', // feed climb glyph (stroke is currentColor)
  '#778e66': 'olive-500', // map climb shapes: their colour (and inherited title text) stays the accent
  '#82966a': { text: 'olive-500' }, // climb history PR tag
  '#748269': 'olive-600', // feed phone rail doors
  '#68775a': { text: 'olive-600' }, // feed rail links
  '#667858': 'olive-600', // feed 'View riding' link and its chevron
  '#586747': { text: 'olive-700' }, // feed card avatar initials
  '#5f7150': { text: 'olive-600' }, // climb light-avatar initials, matching its other light avatar (the feed rail's are olive-700 by selector)
  '#688348': 'olive-500', // feed network dot hover and other uses; the dots themselves are opaque sage-300 by selector
  '#fcfff4': 'card', // white rings on the network dots
};

// Context the colour alone can't tell: a selector fragment (and optionally a property family) to a token.
// The first matching entry wins.
export const LEGACY_SELECTORS: Array<{ selector: string; property?: string; token: string; alpha?: number }> = [
  { selector: '.f3-context-link:hover', property: 'color', token: 'olive-700' },
  { selector: '.f3-context-link', property: 'color', token: 'olive-600' },
  { selector: '.f3-rail-heading h2', property: 'color', token: 'ink-2' },
  { selector: '.p6-shell nav', property: 'color', token: 'band-muted' }, // profile inactive nav on the band; #cbd0c8 elsewhere is calendar type on paper
  { selector: '.p6-map .m2-map-controls', property: 'background', token: 'raised' },
  // A property names its family (background also covers background-color); a custom property must match exactly.
  { selector: '.c10-page', property: '--c10-avatar-ink', token: 'olive-600' },
  { selector: '.c10-page', property: '--c10-avatar', token: 'sage-100' }, // the climb PB disc: its custom property names no role, so the per-role entry can't reach it
  { selector: '.f4-map-attribution', property: 'color', token: 'ink-2' }, // map attributions are ink-2 in every room (the climb's #69775d is otherwise an ink-3 hold)
  // The viewer's own avatar in the feed rail matches their avatar on the post beside it: a neutral disc, olive initials.
  { selector: '.f3-person-identity .f2-avatar', property: 'background', token: 'rule' },
  { selector: '.f3-person-identity .f2-avatar', property: 'color', token: 'olive-700' },
  // Feed network activity dots are drawn opaque in the activity fill, so they read as sage over land and sea alike.
  { selector: '.f3-world-dot::before', property: 'background', token: 'sage-300', alpha: 1 },
];
