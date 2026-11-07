# BoulderScan Mobile Readiness Spec

Research date: 2026-03-23

---

## Part 1: Etherscan Mobile Patterns

### Navigation

**Desktop:** Horizontal top bar with logo left, nav links center (Home, Blockchain dropdown, Tokens dropdown, NFTs, Resources, Developers, More), and a search icon + sign-in button right. Links use dropdowns that expand on hover.

**Mobile (< ~768px):** Collapses to a hamburger menu (three horizontal lines) on the left side of the header. Tapping the hamburger opens a full-height slide-out drawer from the left. The drawer contains all nav items as stacked vertical links with expandable sub-sections (accordion-style). The search bar remains visible in the header as a magnifying glass icon that, when tapped, expands to a full-width search input overlay. Logo remains centered or left-aligned. No bottom navigation bar -- Etherscan keeps everything in the top hamburger drawer.

**Why it works:** Block explorers are reference tools, not daily apps. Users land on specific pages via links. A hamburger is sufficient because nav is secondary to the content on the page you're already viewing. Bottom bars are for apps with 3-5 frequent destinations (social feeds, tabs). Etherscan's information architecture is too deep (dozens of pages) for a bottom bar.

### Transaction Pages

**Desktop:** Two-column or wide single-column layout. Key-value rows with label left, value right, spanning the full width. Additional detail sections below (logs, internal transactions, state changes).

**Mobile:** Same key-value row layout but the rows stack vertically -- label on top, value below. Long values (hashes, addresses) are truncated with ellipsis and show copy buttons. The page becomes a long vertical scroll. Section headers remain as sticky dividers. "More Details" sections that were initially collapsed on desktop remain collapsed on mobile too, saving vertical space.

**Key pattern: No horizontal scrolling.** Everything reflows to single column.

### Address Pages

**Desktop:** Hero area with address + balance + USD value. Tabs below: Transactions, Internal Txns, Token Transfers (ERC-20), NFT Transfers, Token Holdings, Analytics, Comments, etc.

**Mobile:** The tab bar converts to a horizontally scrollable pill/chip row. Only 2-3 tabs visible at a time; user swipes to see more. The transaction list within tabs becomes card-based rather than tabular: each transaction renders as a bordered card with stacked fields (Txn Hash, Method, Block, Age, From, To, Value, Fee). Column headers disappear. Each field is labeled inline with small uppercase text above the value.

**Why it works:** Tabs-to-scrollable-pills preserves all content while making the interface thumb-friendly. Card layout per transaction gives each field room to breathe without requiring a 7-column table.

### Search

**Desktop:** Large search bar always visible in the header area with placeholder text and a search button.

**Mobile:** The search bar collapses to a magnifying glass icon in the header. Tapping it opens a full-screen search overlay with the input field, placeholder, and a close button. This prevents the search bar from consuming header real estate on small screens.

**BoulderScan note:** Our search band is more prominent than Etherscan's (it's a full section below the header, not inline). This will need special treatment.

### Data Tables

This is Etherscan's most important mobile pattern. They use three strategies depending on the table:

1. **Card layout (primary pattern):** Each table row becomes an individual card with each cell labeled and stacked vertically. Column headers are hidden. Each value is preceded by a small uppercase label. This is used for transaction lists, token transfers, and most list views.

2. **Column hiding:** For simpler tables (e.g., block list), less important columns are hidden entirely on mobile. For instance, the "Gas Used" and "Gas Limit" columns disappear, keeping only Block, Age, Txns, and Reward.

3. **Horizontal scroll (rare):** Only used for tables where column relationships are critical and card layout would lose meaning (e.g., log data, raw ABI decoding). A subtle horizontal scroll indicator (fade gradient on the right edge) signals scrollability.

**The decision tree:**
- Is each row a "thing" users want to scan? -> Card layout
- Are columns few and simple? -> Column hiding
- Is the table structural/technical? -> Horizontal scroll

### Copy Buttons

**Desktop:** Small clipboard icon appears on hover next to addresses and hashes.

**Mobile:** The copy icon is always visible (no hover state on touch devices). Icons are slightly larger (minimum 44x44px touch target). After tapping, a brief "Copied!" toast or inline label change confirms the action.

**Etherscan's approach:** They use a persistent small icon (no hover gating). This is correct for mobile -- hover states are invisible to touch users.

### Hex Data / Long Strings

**Desktop:** Addresses shown in full with monospace font. Transaction hashes shown in full.

**Mobile:** Aggressive truncation everywhere:
- Addresses: `0x1234...abcd` (first 6 + last 4 characters)
- Transaction hashes: `0x1234...abcd` (first 6 + last 4)
- Full value always available via copy button
- The truncated text uses `overflow-wrap: anywhere` as a fallback so if the container forces wider display, the text wraps at any character rather than overflowing

**Critical detail:** Etherscan NEVER lets a monospace string cause horizontal overflow. Truncation is enforced at the component level, not via CSS overflow hidden.

### Gas Tracker / Stats Widgets

**Desktop:** 3-4 stat widgets in a horizontal row (Gas Price, ETH Price, Market Cap, etc.)

**Mobile:** Widgets collapse to a 2-column grid. If there are 3 items, the third goes full-width below. Labels shrink. Values maintain large font weight for scannability. Some secondary detail text (% change, etc.) is hidden.

### What Etherscan DOESN'T Show on Mobile (Intentional Degradation)

- **Sidebar ads** -- completely removed
- **Analytics charts** -- hidden or replaced with a "View on Desktop" link
- **Multi-column comparison views** -- collapse to single-column stacked
- **Detailed gas breakdown** in transaction pages -- collapsed behind "More Details"
- **Comment sections** -- moved below fold
- **Internal transaction traces** (deep tree views) -- still present but collapsed by default
- **Some dropdown sub-navigation items** -- simplified to fewer options
- **Hover tooltips** -- replaced with inline text or long-press

**Philosophy:** Etherscan's mobile degradation preserves all *data* but simplifies *interaction*. Nothing is truly deleted; it's progressively disclosed.

---

### Solscan Mobile Comparison

Solscan (Solana's primary explorer) takes a similar but slightly different approach:

**Navigation:** Bottom tab bar with 4 items (Home, Tokens, NFTs, DeFi) plus a floating search icon. This is more app-like than Etherscan's hamburger approach. Makes sense for Solscan because their information architecture is shallower (fewer page types).

**Tables:** More aggressive card conversion. Token holdings are shown as a vertical list of cards with token icon, name, balance, and USD value per card. Transaction lists also use cards.

**Addresses:** Truncated to 4+4 characters on mobile. Always paired with a copy icon.

**Stats:** Dashboard stats use a scrollable horizontal carousel of cards rather than a grid. You swipe left/right through stats.

**What Solscan hides:** DeFi protocol breakdowns, detailed analytics, validator info. These become "tap to expand" sections.

**Key difference from Etherscan:** Solscan is more opinionated about hiding things. Etherscan shows everything but reorganized; Solscan actively hides secondary data behind taps. For BoulderScan, the Etherscan approach (reorganize, don't hide) is better because we have less content overall -- hiding would make pages feel empty.

---

## Part 2: Current BoulderScan Mobile State

### Existing Responsive Infrastructure

The codebase has **three breakpoints** already defined in `index.css`:

| Breakpoint | Width | Current Purpose |
|-----------|-------|-----------------|
| `1100px` | Tablet landscape | Grid collapse: hero panel, page-columns, kv-grid go 1-col. Data table goes 2-col. Detail rows stack vertically. Climb visual panels go 1-col. |
| `720px` | Tablet portrait / large phone | Header stacks vertically. Search input/button stack. Data table goes 1-col. Nav/actions wrap. Liveness chips after first hidden. Touch target 44px. Card-mobile data tables hide headers, show labels. Data-table-scroll enabled with min-width 540px. Climb visual heights reduced to 160px. |
| `480px` | Small phone | Tighter padding. Search label/caption hidden. Brand name shrinks to 22px. KV-grid forced to 2-col. Status pill in actions hidden. |

**Assessment:** The responsive foundation is surprisingly solid. Three well-chosen breakpoints, progressive disclosure for data tables (`data-table--card-mobile`), horizontal scroll wrappers (`data-table-scroll`), touch target enforcement. However, **not all pages use the mobile-ready patterns**.

### Per-Page Mobile Assessment

#### Observatory Page (home)

**Current state at 375px:**

1. **Hero panel** -- Goes to 1-col at 1100px (CSS rule exists). Text column on top, stat rail below. Stat rail stays 2x2 grid. **Works acceptably.**

2. **Page columns (Top Vaults / Recent Events)** -- Goes to 1-col at 1100px. **Works.**

3. **Top Vaults data table** -- This is the problem child. The table uses `data-table-scroll` wrapper which enables horizontal scrolling at 720px with `min-width: 540px` (reduced to 480px at 480px). The table has 4 columns (Vault, Climb, Stake, KOM). At 375px, this forces horizontal scroll. **The table does NOT use `data-table--card-mobile` class**, so it keeps the tabular layout with scroll rather than converting to cards.

4. **Supply State stat cards** -- Uses `card-grid--four` which goes to 2-col at 720px. **Works.**

5. **Recent Events feed** -- Feed items are inherently vertical/card-based. **Works well on mobile.**

**Verdict:** One problem -- the Top Vaults table needs card-mobile treatment.

#### Vault Page

**Current state at 375px:**

1. **Hero panel** -- Same as Observatory, works fine at 1-col.

2. **ClimbVisual** -- Panels go 1-col at 1100px (map stacks over profile). Heights drop to 160px at 720px. Trait cards use `auto-fit, minmax(120px, 1fr)` which naturally reflows. **Works well.**

3. **Economics stat cards (card-grid--four)** -- Goes to 2-col at 720px. **Works.**

4. **Page-columns sections** -- All go 1-col at 1100px. **Works.**

5. **Vault State kv-grid** -- Goes to 1-col at 1100px, then back to 2-col at 480px. **Works.**

6. **Leaderboard data table** -- Uses `data-table-scroll` wrapper. 4 columns (Rank, Rider, Time, Recorded). At 375px, horizontal scroll with min-width. **Does NOT use card-mobile.** The rider column contains `AddressDisplay` with copy button which can be wide.

7. **Distribution History data table** -- Same scroll wrapper pattern. 4 columns (Epoch, Transaction, Distributed, Time). The Transaction column has addr-group with monospace link. **Does NOT use card-mobile.**

8. **Local Legend card** -- Legend card is already card-based with flex-wrap. **Works fine.**

9. **Collapsible (Technical Details)** -- Collapsed by default. When open, contains kv-grid and detail-list which both handle mobile via existing breakpoints. **Works.**

10. **Recent Activity feed** -- Card-based feed items. **Works.**

**Verdict:** Two problems -- Leaderboard and Distribution History tables need card-mobile.

#### Transaction Page

**Current state at 375px:**

1. **Hero panel** -- Works. The `mono-heading` hash with `word-break: break-word` prevents overflow. At 480px, mono-heading drops to 14px. **Works.**

2. **Page-columns (Overview / Transaction Meta)** -- Goes 1-col. **Works.**

3. **Overview detail-list** -- Detail rows stack vertically at 1100px. **Works.**

4. **Transaction Meta detail-list** -- Same. The full signature in the Signature row is monospace with `word-break: break-word` on the value side. At 375px this is a very long string that wraps. **Works but looks cluttered.** Could benefit from truncation.

5. **Instructions stack-list** -- Each instruction is a `stack-card`. The body uses `stack-card__body` which is a 2-col grid (Arguments / Accounts side by side). At 1100px this collapses to 1-col. Within each side, `detail-list` rows stack. **Works but gets very long vertically.**

6. **Events stack-list** -- Same pattern as instructions. **Works.**

7. **Raw JSON disclosures** -- `<pre>` with `overflow: auto`. At 375px the JSON scrolls horizontally within the `<pre>` block. **Acceptable.**

**Verdict:** Mostly works. Full signature display in Transaction Meta should truncate on mobile. The page gets very long but nothing breaks.

#### Account Page

**Current state at 375px:**

1. **Hero panel** -- Works. Same pattern as others.

2. **Page-columns (Balances / Protocol State)** -- Goes 1-col. **Works.**

3. **KV grids** -- Go 1-col at 1100px, back to 2-col at 480px. **Works.** The pubkey in Protocol State is monospace with `overflow-wrap: anywhere`. **Works but looks dense.**

4. **Active Stakes data table** -- **Uses `data-table--card-mobile` class.** Headers hidden at 720px, rows become cards with `data-label` attributes generating inline labels. **This page already has the correct mobile pattern.**

5. **Completions data table** -- Also uses `data-table--card-mobile`. **Correct mobile pattern.**

6. **Beetle Cards stack-list** -- Card-based with kv-grid inside. **Works.**

7. **Recent Activity feed** -- Card-based. **Works.**

**Verdict:** The Account page is the most mobile-ready page. Tables already use card-mobile pattern. Only minor polish needed.

#### Global Elements

1. **Site header** -- At 720px, inner flexes to column. Brand on top, then actions/nav wrap. At 480px, status pill hidden, brand shrinks. **Works but the nav pills + brand + status pill all wrapping can look messy at exactly 720px.** The nav area has no hamburger; all pills are visible and wrap.

2. **Search band** -- At 720px, input row stacks (input on top, button full-width below). Form header stacks. At 480px, search label and caption hidden. **Works functionally.** The search band takes significant vertical space on mobile.

3. **Footer** -- Flex-wrap with centered items. **Works fine at all sizes.**

4. **CopyButton** -- Always visible (no hover gating). 14x14px icon which is small for touch. The button itself has padding:2px, making the touch target only ~18x18px. **Below 44px minimum touch target.** Already has 44px enforcement in the 720px breakpoint for nav links but NOT for copy buttons specifically.

---

## Part 3: Gap Analysis + Implementation Spec

### Breakpoint Strategy

Keep the existing three breakpoints. They are well-chosen:

| Token | Width | Purpose |
|-------|-------|---------|
| `--bp-tablet` | `1100px` | Two-col to one-col grid collapse |
| `--bp-phone` | `720px` | Mobile layout, stacked inputs, card tables, touch targets |
| `--bp-small` | `480px` | Small phone polish, tighter padding, element hiding |

No additional breakpoints needed. The 375px iPhone SE viewport falls within the 480px rules, which is correct.

### Priority-Ranked Implementation Items

#### P0 -- Broken or Unusable on Mobile

**1. Top Vaults table (Observatory) -- Convert to card-mobile**

The Top Vaults table is the most visible mobile breakage. It uses horizontal scroll on a 4-column grid, which at 375px forces the user to scroll a 480-540px wide table in a 375px viewport.

*Current markup in ObservatoryPage.tsx:*
```html
<div className="data-table-scroll">
  <div className="data-table">
```

*Change to:*
```html
<div className="data-table data-table--card-mobile">
```

Remove the `data-table-scroll` wrapper. Add `data-label` attributes to each cell:
- Cell 1: `data-label="Vault"`
- Cell 2: `data-label="Climb"`
- Cell 3: `data-label="Stake"`
- Cell 4: `data-label="KOM"`

The existing `.data-table--card-mobile` CSS at the 720px breakpoint will handle the rest (header hidden, rows become cards with generated labels).

**2. Leaderboard table (Vault Page) -- Convert to card-mobile**

Same pattern as above. Currently uses `data-table-scroll`. Switch to `data-table--card-mobile` with `data-label` attributes:
- Cell 1: `data-label="Rank"`
- Cell 2: `data-label="Rider"`
- Cell 3: `data-label="Time"`
- Cell 4: `data-label="Recorded"`

**3. Distribution History table (Vault Page) -- Convert to card-mobile**

Same conversion:
- Cell 1: `data-label="Epoch"`
- Cell 2: `data-label="Transaction"`
- Cell 3: `data-label="Distributed"`
- Cell 4: `data-label="Time"`

#### P1 -- Functional But Poor UX

**4. CopyButton touch target**

The copy button is 14x14px icon with 2px padding = ~18px touch target. Mobile guidelines require 44px minimum.

*CSS change in index.css, inside the `@media (max-width: 720px)` block:*
```css
.copy-button {
  min-width: 44px;
  min-height: 44px;
  padding: 8px;
}
```

This expands the tap area without changing the visible icon size.

**5. Search band vertical space on mobile**

The search band with its label, caption, liveness strip, input, button, and helper text takes ~200px+ of vertical height on mobile. This pushes actual page content below the fold.

*Recommended approach:*
At 720px:
- Liveness strip: already hiding non-first chips. Keep this.
- Search label + caption: already hidden at 480px. Move this to 720px.

At 480px:
- Collapse the search to a single-line input with inline button (no form chrome).
- OR: Collapse the search band behind a magnifying glass icon that expands on tap (Etherscan pattern). This is a component change in ExplorerShell.tsx.

Recommended: Start with moving label/caption hide to 720px. The full collapse-behind-icon is a larger change that can come later.

*CSS change:*
```css
@media (max-width: 720px) {
  .search-label,
  .search-band__caption {
    display: none;
  }
}
```

(Currently these hide at 480px. Moving to 720px saves one line of vertical space on phones.)

**6. Header nav wrapping**

At 720px the header stacks vertically, but with only 1 nav item (Observatory) plus the BoulderRoller external link, the wrapping looks sparse. As more nav items are added (Vault explorer, etc.), this will get cluttered.

*For now:* No change needed. When nav grows to 3+ items, implement a hamburger. The current 1-2 item state works fine as horizontal pills even on mobile.

*Future-proofing CSS suggestion:*
```css
@media (max-width: 720px) {
  .site-nav {
    overflow-x: auto;
    flex-wrap: nowrap;
    -webkit-overflow-scrolling: touch;
  }
}
```

This would make nav pills horizontally scrollable instead of wrapping. Not needed yet.

**7. Full signature display in Transaction Meta**

The Transaction Meta section shows the full Solana signature (88 characters, base58) in a detail-row value. On mobile this wraps across 4+ lines of monospace text.

*Recommended:* On mobile, truncate to `shortenAddress(signature, 8)` in the detail-row display (the hero already shows a truncated version). The CopyButton is right there for the full value.

This requires a component change in TransactionPage.tsx -- wrap the full signature display in a responsive conditional, or add a CSS class that truncates with ellipsis on mobile:

```css
@media (max-width: 720px) {
  .detail-row__value--mono {
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}
```

Caution: This may affect other detail-row values that should wrap. Apply this class narrowly (only on the Transaction Meta signature row) rather than globally.

#### P2 -- Polish and Refinement

**8. Stat card value font size at 375px**

Stat card values use `clamp(18px, 2vw, 24px)`. At 375px, `2vw = 7.5px`, which clamps to the 18px minimum. This is fine, but the "CAL" / "DUNG" unit suffix can make lines long.

*Recommendation:* No CSS change needed. The 18px minimum is readable. If units cause overflow, the fix is in the format functions (abbreviate to "K" / "M"), not in CSS.

**9. Event feed item touch targets**

Feed items contain multiple tappable elements (tx signature link, vault link, account links). These are small text links that may be hard to tap precisely.

*CSS change at 720px:*
```css
@media (max-width: 720px) {
  .feed-context__link,
  .mono-link {
    display: inline-block;
    padding: 6px 2px;
  }
}
```

This already exists in the 720px media query. Verify it applies to feed items (it should, since `.mono-link` and `.feed-context__link` are the correct selectors).

**10. ClimbVisual on small phones**

At 375px, the climb visual map and profile panels are 160px tall each (320px total stacked). The trait cards auto-fit at minmax(120px). With 3 traits at 375px, this yields a single row of 3 cards (~125px each). With 4 traits (terrain included), it becomes 2 rows of 2.

*Assessment:* Works fine. No change needed. Consider reducing panel heights to 140px at 480px if the page feels too tall.

**11. Instruction card internal layout (Transaction Page)**

The instruction `stack-card__body` is a 2-col grid (Arguments left, Accounts right) that goes 1-col at 1100px. At 375px, the arguments detail-list and accounts detail-list stack vertically. Each can get quite long.

*Recommendation:* Add a slight visual separator between the Arguments and Accounts sections when stacked:

```css
@media (max-width: 1100px) {
  .stack-card__body > div + div {
    padding-top: 10px;
    border-top: 1px solid var(--panel-border);
  }
}
```

**12. KV-grid cell density at 480px**

At 480px, kv-grid is forced back to 2-col (`grid-template-columns: repeat(2, minmax(0, 1fr))`). This is good for short values but problematic when a cell contains a full pubkey with copy button (Account Page, Protocol State section). The pubkey wraps within a ~170px cell.

*Recommendation:* For cells containing monospace addresses, truncate to 4+4 chars. This is already happening via `AddressDisplay` component (which uses `shortenAddress` with `chars=4` default), but the Protocol State section renders the full pubkey:

```jsx
<strong className="mono-inline addr-group">{data.pubkey}<CopyButton text={data.pubkey} /></strong>
```

This should use `shortenAddress(data.pubkey)` on mobile. The most pragmatic fix is to always use the shortened version here since the CopyButton provides the full value.

---

### Summary Table

| Priority | Item | Page | Type | Effort |
|----------|------|------|------|--------|
| P0 | Top Vaults table -> card-mobile | Observatory | Markup + data-label | Small |
| P0 | Leaderboard table -> card-mobile | Vault | Markup + data-label | Small |
| P0 | Distribution History table -> card-mobile | Vault | Markup + data-label | Small |
| P1 | CopyButton 44px touch target | Global | CSS | Tiny |
| P1 | Search band reduce vertical space | Global | CSS | Tiny |
| P1 | Transaction signature truncation | Transaction | CSS | Small |
| P1 | Header nav future-proofing | Global | CSS | Tiny (deferred) |
| P2 | Instruction card separator when stacked | Transaction | CSS | Tiny |
| P2 | KV-grid pubkey truncation | Account | Component | Small |
| P2 | ClimbVisual height at 480px | Vault | CSS | Tiny |

### What to HIDE on Mobile vs What to REFLOW

Following Etherscan's philosophy: **reflow everything, hide almost nothing.** BoulderScan has less content than Etherscan, so hiding would make pages feel empty.

**Hide on mobile (already implemented):**
- Liveness chips after the first one (720px) -- correct, secondary health info
- Search label + caption (480px, recommend moving to 720px) -- correct, placeholder text is sufficient
- Status pill in header actions (480px) -- correct, external link is low priority

**Hide on mobile (recommended additions):**
- None. Everything else should reflow, not hide.

**Reflow on mobile:**
- All data tables: card layout (P0 items above)
- All 2-col grids: 1-col stack (already done)
- Hero panels: 1-col (already done)
- Detail rows: label-above-value (already done)

**Keep visible on mobile (do not hide):**
- Search band (it's the primary interaction -- collapse but don't remove)
- All stat cards (they're the page payload)
- Copy buttons (they're more important on mobile than desktop)
- Feed items (already mobile-friendly)
- Raw JSON disclosures (collapsed by default, user-initiated)

### CSS Implementation Notes

All changes go into the existing media query blocks in `web/scan/src/index.css`. No new CSS files or Tailwind dependencies needed. The codebase uses vanilla CSS with CSS custom properties, and all responsive work should follow this pattern.

The `data-table--card-mobile` pattern is already fully implemented in CSS. The P0 items are purely markup changes (adding the class and `data-label` attributes to existing components).

The dark mode overrides at the end of `index.css` do not need changes -- the responsive rules are not color-dependent, and the dark mode block only overrides colors/backgrounds.
