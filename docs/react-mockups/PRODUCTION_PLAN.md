# React Mockup → Production-Ready Expansion Plan

## Current Stubs Identified

### 1. **UI Component Stubs**
- ❌ **Alerts** → Using `alert()` instead of Modal system
- ❌ **Icons** → Limited hand-coded SVG set (only 4 icons)
- ❌ **Tooltips** → No hover explanations for features
- ❌ **Loading States** → No spinners or skeleton screens
- ❌ **Error States** → No error boundaries or messages

### 2. **Data & State Stubs**
- ❌ **Mock Data** → Hard-coded arrays, no persistence
- ❌ **No LocalStorage** → State doesn't persist across refreshes
- ❌ **No API Simulation** → Instant responses, no loading
- ❌ **No Pagination** → All data rendered at once

### 3. **Feature Stubs**
- ❌ **Pile Details** → Alert instead of detailed modal
- ❌ **Staking Interface** → No actual staking form
- ❌ **Charts/Graphs** → No TSS over time, APY trends, etc.
- ❌ **Search/Filter** → No way to filter piles or history
- ❌ **Notifications** → No toast system for actions
- ❌ **Settings Panel** → No preferences/customization

### 4. **Visual Stubs**
- ❌ **Beetle Visualization** → Just placeholder div
- ❌ **Map** → Basic grid, not interactive tile map
- ❌ **Wardrobe Items** → Text-only, no actual visuals
- ❌ **Progress Bars** → No animated progress indicators
- ❌ **Sparklines** → No inline trend visualization

## Proposed Production Features

### Phase 1: Core UI Components (Priority)
```javascript
✅ Modal System
   - PileDetailModal (stake/view stats)
   - StakingModal (deposit/withdraw)
   - ConfirmationModal (transactions)
   - WardrobeDetailModal (NFT stats)

✅ Toast Notification System
   - Success/Error/Warning/Info toasts
   - Auto-dismiss with countdown
   - Action buttons in toasts
   - Stack multiple notifications

✅ Full Icon Library
   - Add 20+ common icons (X, Check, Info, Warn, etc.)
   - Dynamic icon components
   - Size/color props

✅ Loading States
   - Button loading spinners
   - Skeleton screens for cards
   - Full-page loading overlay
   - Progressive data loading
```

### Phase 2: Data Visualization
```javascript
✅ TSS Chart (Dashboard)
   - 30-day line chart using SVG
   - Interactive tooltips on hover
   - Trend indicators

✅ APY Chart (Piles)
   - Historical APY visualization
   - Multi-pile comparison

✅ Sparklines
   - Inline trend vis in tables
   - 7-day activity sparklines

✅ Progress Bars
   - CAL usage (animated)
   - Coherence score
   - Staking rewards progress
```

### Phase 3: Forms & Interactions
```javascript
✅ Staking Interface
   - Input validation
   - Max button (stake all available)
   - Lock duration selector
   - APY calculator preview
   - Transaction signing flow

✅ Search & Filter
   - Pile search by name/type
   - History date range filter
   - Multi-select pile types
   - Sort by (APY, TVL, Name)

✅ Pagination
   - 10/25/50/100 items per page
   - Page navigation
   - Jump to page input
```

### Phase 4: Advanced Features
```javascript
✅ Settings Panel
   - Theme toggle (keep Elemental)
   - Notifications preferences
   - Default stake duration
   - Display currency (DUNG/USD)

✅ Leaderboard View (new tab)
   - Top beetles by TSS
   - Top piles by pot size
   - Personal rank indicators

✅ Wallet Connection
   - Mock wallet adapter
   - Sign transaction flow
   - Transaction history

✅ Real-time Updates
   - Simulated price feed
   - Live pile pot updates
   - Countdown timers (epoch end)
```

## Implementation Strategy

### Option A: Single Mega-File ⚡ (Recommended for Demo)
**Pros:**
- Self-contained, easy to share
- No build step required
- Works offline immediately

**Cons:**
- Large file (~150KB)
- Harder to navigate code

**File Structure:**
```
docs/react-mockups/
└── index.html (complete production UI)
```

### Option B: Multi-File Structure 📁
**Pros:**
- Better code organization
- Easier to maintain
- Modular components

**Cons:**
- Requires local server
- More complex setup

**File Structure:**
```
docs/react-mockups/
├── index.html
├── components/
│   ├── Modal.js
│   ├── Toast.js
│   ├── Chart.js
│   └── Forms.js
├── utils/
│   ├── storage.js
│   └── mock-api.js
└── styles.css
```

## Next Steps

### Immediate Action Required:
1. **Choose Implementation Option** (A or B)
2. **Prioritize Features** (All phases or specific subset?)
3. **Confirm Scope** (Is this still a "mockup" or becoming a mini-app?)

### Estimated Complexity:
- **Phase 1 Only**: ~500 lines added
- **Phases 1-2**: ~1000 lines added
- **Phases 1-3**: ~1500 lines added
- **All Phases**: ~2500 lines added (full production)

### Time to Implement:
- **Quick (Phase 1)**: Essential UI components
- **Medium (Phases 1-2)**: + Data visualization
- **Full (All Phases)**: Complete production-ready prototype
