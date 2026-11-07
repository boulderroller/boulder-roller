# Profile Candidate V6

Local workshop candidate, 14 September 2026. No production integration or deployment.

## Accepted design

**Locked by the user on 14 September 2026** after the Feed V9 consistency audit. Profile V6 at `934b51321dc6443208ed8e568a0156b78c902919` is the accepted visual and interaction baseline for implementation.

Preserve the personal banner/portrait, neutral ground and darker typography, clustered climb standing with accepted RankMarks and right-aligned best times, adjacent recent-rides composition, terrain relationship, secondary four-week chart, and owner-only economic context. Preserve the reviewed ordering and proportions; do not redesign these sections during implementation.

The agreed small implementation cleanup is to remove the generic trophy icon beside “Personal best,” retaining its text and result. This acceptance record does not alter the reviewed candidate rendering or any earlier generation.

This locks the Profile design direction. It does not authorize production integration/deployment or turn illustrative rider, media or economic examples into live evidence. Real data, authorization and action contracts remain the implementation boundaries described below.

Open `http://localhost:4350/?surface=profile&variant=profile-v6&scenario=rider&viewer=owner&tab=overview&state=ready`.
Run from `web/portal` with `npm run workshop -- --port 4350`. V5 remains on 4337; occupied 4338/4339 servers were left untouched.

## Design delta

V5 was rejected as too clinical. V6 keeps its personal banner, portrait, riding history and accepted terrain, but moves the interface onto neutral ground with darker text. RankMarks gather in a compact vertical list: each mark, hill and best time stays together. The map follows those hills in the same column; a wider recent-rides column supplies everyday activity and photographs. The four-week chart remains secondary and interactive.

Owner-only economic context attaches to the same objects. Supplied CAL counted appears on its ride. CAL deposited and DUNG ready/pending appear on the corresponding climb, and selecting that line opens the matching position in Portfolio. Keyboard entry focuses the Portfolio heading; returning restores the originating hill and scroll position. Sporting rank and economic position remain independent.

All Profile V1–V5, Ride, Feed, Climb, Map and baseline files remain unchanged.

## Truth and privacy boundaries

- The fictional Alex profile, generated photographs, twelve authored ride summaries, sporting standings and new economic examples are **illustrative**, continuously identified by the workshop. They are not real rider, Vault, balance, settlement or chain evidence.
- The same complete 28-day history totals 558.2km and 6,770m across twelve rides. Partial history does not produce complete-period totals.
- Illustrative owner positions are explicitly bound to Alex and the supplied canonical hills: Wises has 320 CAL deposited and no supplied DUNG state; Sprague has 940 CAL deposited and 3.6 DUNG ready. The rank does not determine either amount. Two authored rides carry 87 and 64 CAL counted. These numbers exist only to exercise the proposed composition.
- Imports enforce rider/hill/ride bindings, unique entries, bounded collections, finite nonnegative amounts, known DUNG states and an observation date no earlier than the referenced counted rides. Unknown fields fail closed. Explicit null means absent; missing economics do not become zeros.
- Visitor projection, preview messages, Data and exports omit the owner economic object. The workshop retains its full source fixture so switching back to Owner and editing does not erase it. Viewer controls simulate product visibility; they are not authentication or production authorization proof. Private scenarios contain no person, rides, standings or economics.
- An additional scenario, “Alex · economics unavailable,” shows the same rider and history with all economic context absent. Balance remains unavailable in every scenario; there are no simulated deposit, withdrawal or collection operations.
- Geography remains Map V7's retained canonical Philadelphia collection. Bounds never become invented route geometry. Ride detail remains a summary with route unavailable. Named hill links open the retained Map V7 climb detail.
- Local edits/imports remain in browser session storage. JSON export transfers them. Sharing a URL does not transfer a custom scenario.

## Verification

166 workshop tests, typecheck and build pass. The build retains the existing large-workshop chunk warning. Focused red-to-green covers the new owner projection/bindings and chronological observation validation. A browser red reproduced lost owner context after a Visitor reload; the correction restores both positions when switching back to Owner.

Browser checks include exact 1440×1000 and 390×844 rendering without horizontal overflow; keyboard position entry and focus/scroll return; Rides search/climb filtering and return; Training totals; calendar focus inspection, empty-day selection and Escape clearing; canonical climb navigation and browser Back; owner/visitor and sparse/new/private/loading/unavailable/offline/no-economy cases. Imported pending DUNG renders correctly. JSON and file imports, rejected unsupported data, V5/V6 switching and custom reload pass. The exported JSON file was read back and checked for the candidate, rider and economic state. Strava reference and squint work; final stable browser logs contain no errors.

Exact final captures are in `evidence/`: desktop overview, phone overview, phone standing/history and phone position detail. Final captures were refreshed after development stylesheet changes so browser Back's restored development document did not supply stale CSS.

## Media provenance

`assets/hills.png` is a 2172×724 fictional photograph generated with the built-in image tool, using V4's fictional portrait/banner as identity references. Its desktop crop uses `object-position: 50% 0%`; phone uses `76% 0%`. The portrait and coffee photograph reuse V4/V5 assets. No image depicts a supplied real rider or claims an actual ride on the canonical hills.

Generation prompt:

> Use case: photorealistic-natural, identity-preserve. Generate ONE wide 3:1 documentary cycling photograph. Both references show the same fictional Alex; preserve the dark-haired, short-bearded man's facial identity from the portrait, and use the banner only as an additional identity reference. A new moment after a hard hilly ride: Alex occupies the right third of the foreground, wearing a matte dark helmet and plain dark unbranded cycling kit, leaning forward with both hands on the drop bars, breathing and looking slightly away toward the street. His expression is quiet and tired, with no posed smile. A modest Philadelphia-like residential hill descends behind him through green street trees and understated brick houses; two small riding companions may be further back. Ordinary overcast late-day light, natural greens and charcoal colors, subtle documentary grain, believable anatomy and bike construction. Unposed personal photograph, no wellness or advertising treatment. Crop-safe composition is essential: the full helmet and face sit in the upper-right region but away from the top edge, centered approximately at x77%, y38%; his forward-leaning shoulders and drop bars stay near the same middle horizontal band. Keep all important human details inside the central 53% of image height so this 3:1 original crops elegantly to a 1240x220 banner. Quiet street and trees occupy the left two-thirds. No literal mud, grunge, extreme film grading, cinematic glow, text, branding, watermark, UI or graphic border. This is fictional workshop imagery, not actual rider evidence.

## Integration handoff

Branch `codex/ij97w-profile-v6`, Bead `boulderroller-v2-ij97w`, visible sibling `/Users/gabetemp/curahee/BoulderRoller-worktrees/profile-v6`. Started from `origin/main` at `a63ffc77f9638b78d3a404be2575aaa7ddd9c145`, carrying full Profile V5 dependency `4b087ad0d1727b0151545bdd410a19206100303c`.

Candidate ownership is `workshop/profile/v6/` and `workshop/tests/profile-v6.test.ts`. Shared registration is a separate commit limited to `main.tsx` and `roomRegistry.ts`: V6 preview dispatch, wrapper import and Profile default. Apply those small registration changes to the current harness, preserving other rooms. Production requires real authorized profile/media/history/standing/economy adapters and actual action contracts; this local candidate does not establish those integrations.
