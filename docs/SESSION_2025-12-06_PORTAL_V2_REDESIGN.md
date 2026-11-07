# Session Exit Document: Portal v2 Redesign Journey

**Date:** 2025-12-06
**Session Type:** Feature Development + Design Overhaul
**Duration:** Extended session (context continuation)

---

## Executive Summary

This session transformed the Boulder Roller portal from a basic sidebar layout to a modern Strava-style 3-column interface. Key deliverables include a working waitlist backend, access gating, profile save functionality, and a complete visual redesign of both the landing page and authenticated app experience.

### Commits Produced
```
4c0c92f feat: Portal v2 redesign - Strava-style layout
a1e9110 feat: Portal UX improvements - waitlist, access gate, save button
28e9eb8 feat(backend): Add /waitlist endpoint for landing page email capture
```

### Starting State
- Stealth landing page with beetle secret entry
- Basic portal with vertical sidebar navigation
- Waitlist form that only logged to console
- No access protection on /app route
- ProfilePanel with auto-save only (no explicit save button)

### Ending State
- Hybrid neo-brutalist landing page with 3px borders and offset shadows
- Horizontal header navigation (Strava-style)
- 3-column layout: Stats | Content | Feed
- Working waitlist → Supabase database
- Access gate protecting /app route
- Explicit Save button on ProfilePanel

---

## Part 1: Initial Request & Discovery

### User's Opening Questions
1. **"Does the waitlist email work?"** → No, it was just `console.log`
2. **"Need contact button"** → `info@boulderroller.com` for outreach/investors
3. **"Lock down /app page"** → Anyone could bypass landing by direct navigation
4. **"Beetle button only works every 3 clicks lmao"** → Intentional! User understood after explanation
5. **"Do we want to adopt this design theme for the whole app?"** → Key design direction question

### Design Direction Discussion

User noted we already had a neo-brutalist design language and asked about adopting the dark stealth theme app-wide. After discussion:

**Decision: Hybrid "Pre-Phase" Approach**
- Landing page: Dark stealth aesthetic with neo-brutalist touches (3px borders, offset shadows)
- App: Keep existing neo-brutalist identity
- Rationale: Landing feels like "exclusive club entrance," app feels like "the club itself"

### Usability Discovery

User asked about ProfilePanel: **"There is no accept button... how can we test for things like this?"**

**Answer:** This is caught by **usability testing** or **QA testing**. The auto-save pattern was confusing users who expected explicit confirmation.

---

## Part 2: Backend Implementation

### 2.1 Waitlist Endpoint

**Created:** `/backend/app/routes/waitlist.py`

```python
@router.post("/waitlist", response_model=WaitlistResponse)
async def add_to_waitlist(
    request: Request,
    payload: WaitlistRequest,
    repo: DatabaseRepository = Depends(get_repository),
) -> WaitlistResponse:
```

**Features:**
- Public endpoint (no auth required)
- Stores email, source, timestamp, IP hash
- Returns success even on duplicate (privacy protection)
- Silent error handling (don't reveal if email exists)

### 2.2 Repository Method

**Added to:** `/backend/app/repositories.py`

```python
async def add_to_waitlist(self, email: str, source: str, ip_hash: int) -> Dict[str, Any]:
    payload = {
        "id": str(uuid.uuid4()),
        "email": email.lower().strip(),
        "source": source,
        "ip_hash": ip_hash,
        "created_at": now.isoformat(),
    }
    await self._run(
        lambda: self._client.table("waitlist")
        .upsert(payload, on_conflict="email")
        .execute()
    )
```

### 2.3 Supabase Table

**Created via SQL:**
```sql
CREATE TABLE waitlist (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  email TEXT UNIQUE NOT NULL,
  source TEXT DEFAULT 'landing',
  ip_hash BIGINT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_waitlist_email ON waitlist(email);
```

### 2.4 Error Encountered & Fixed

**Problem:** Pydantic's `EmailStr` requires `email-validator` package, which wasn't installed.

**Solution:** Replaced with simple regex validation:
```python
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

@field_validator("email")
@classmethod
def validate_email(cls, v: str) -> str:
    v = v.strip().lower()
    if not EMAIL_REGEX.match(v):
        raise ValueError("Invalid email format")
    return v
```

### 2.5 Deployment Verification

```bash
# Test on production
curl -X POST https://api.boulderroller.com/waitlist \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "source": "landing"}'

# Verify in database
SELECT * FROM waitlist ORDER BY created_at DESC LIMIT 5;
```

---

## Part 3: Frontend Implementation - Phase 1 (Wiring)

### 3.1 Waitlist Form → API

**File:** `/web/portal/src/app/page.tsx`

```typescript
const handleEmailSubmit = async (e: React.FormEvent) => {
  e.preventDefault();
  if (email.includes('@')) {
    try {
      await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'https://api.boulderroller.com'}/waitlist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, source: 'landing' }),
      });
    } catch {
      // Silent fail - still show success to user
    }
    setEmailSubmitted(true);
    setEmail('');
  }
};
```

### 3.2 ProfilePanel Save Button

**File:** `/web/portal/src/components/ProfilePanel.tsx`

Added `handleSaveAll` function that:
1. Collects all changed fields (userName, bio, ftp, weight, theme)
2. Makes single PUT to `/users/me`
3. Shows saving/saved state feedback
4. Calls `refetchUser()` on success

```typescript
const handleSaveAll = async () => {
  setSaving(true);
  const updates: Record<string, unknown> = {};
  // ... collect changed fields
  if (Object.keys(updates).length > 0) {
    await api.put('/users/me', updates);
    refetchUser();
  }
  setSaveStatus('saved');
};
```

### 3.3 /app Access Gate

**File:** `/web/portal/src/app/app/layout.tsx`

```typescript
useEffect(() => {
  if (typeof window !== 'undefined' && tokensRehydrated) {
    const hasInviteAccess = sessionStorage.getItem('br_access') === 'granted';
    // Allow if: has invite access OR is authenticated
    if (!hasInviteAccess && !isAuthenticated) {
      window.location.href = '/';
      return;
    }
    setAccessChecked(true);
  }
}, [isAuthenticated, tokensRehydrated]);
```

**Logic:**
- Invite code sets `sessionStorage.br_access = 'granted'`
- Authenticated users always have access
- Unauthenticated without invite → redirect to landing

### 3.4 Contact Link

**Added to footer:**
```typescript
<a href="mailto:info@boulderroller.com">
  info@boulderroller.com
</a>
```

---

## Part 4: Frontend Implementation - Phase 2 (Redesign)

### 4.1 Landing Page: Hybrid Neo-Brutalist Styling

**Key Changes:**

| Element | Before | After |
|---------|--------|-------|
| Border width | 1px | 3px |
| Shadows | None | `4px 4px 0 rgba(255,255,255,0.04)` |
| Beetle | Plain | Decorative frame on hover |
| Tagline | Plain text | Decorative lines on sides |
| Form elements | Minimal | Substantial, chunky |
| Success message | Plain "noted." | Bordered container with checkmark |
| Click hints | Periods (. ..) | Square dots with pulse animation |
| Footer brand | Plain text | Bordered box |
| Background | Solid | Grid overlay + noise texture |

**New CSS Variables:**
```css
--stealth-border: #1f1f1f;
--stealth-border-hover: #2a2a2a;
--shadow-offset: 4px 4px 0 rgba(255, 255, 255, 0.04);
--shadow-offset-hover: 6px 6px 0 rgba(255, 255, 255, 0.06);
```

### 4.2 Header: Strava-Style Horizontal Nav

**File:** `/web/portal/src/components/Header.tsx` (complete rewrite)

**Layout:**
```
┌──────────────────────────────────────────────────────────┐
│ 🪲 BOULDER   [Home] [Rides] [Piles] ...   ⚡123  🔔  👛 │
│    ROLLER                                                │
└──────────────────────────────────────────────────────────┘
```

**Features:**
- Brand on left (stacked BOULDER / ROLLER)
- Color-coded nav items in center
- Compact energy display with progress bar
- Notifications + Profile on right
- Mobile drawer for small screens
- Hover lift animations

**Nav Items:**
```typescript
const NAV_ITEMS = [
  { id: 'home', label: 'Home', icon: Home, colors: ['--purple', '--pink'] },
  { id: 'rides', label: 'Rides', icon: Activity, colors: ['--blue', '--cyan'] },
  { id: 'piles', label: 'Piles', icon: MapPin, colors: ['--green', '--cyan'] },
  { id: 'portfolio', label: 'Portfolio', icon: TrendingUp, colors: ['--orange', '--yellow'] },
  { id: 'challenges', label: 'Challenges', icon: Trophy, colors: ['--purple', '--orange'] },
  { id: 'feed', label: 'Feed', icon: Users, colors: ['--pink', '--purple'] },
  { id: 'discover', label: 'Discover', icon: Compass, colors: ['--cyan', '--green'] },
];
```

### 4.3 3-Column Layout

**File:** `/web/portal/src/app/app/layout.tsx` (major rewrite)

**Structure:**
```
┌────────────────────────────────────────────────────────┐
│                      HEADER                             │
├───────────┬────────────────────────────┬───────────────┤
│  STATS    │         CONTENT            │     FEED      │
│  PANEL    │                            │     PANEL     │
│           │                            │               │
│  • Energy │     (Tab Content)          │  • Activity   │
│  • Rank   │                            │  • Leaderboard│
│  • Weekly │                            │  • Upcoming   │
│    Stats  │                            │               │
└───────────┴────────────────────────────┴───────────────┘
```

**Grid:** `grid-cols-12`
- Left: `col-span-3 xl:col-span-2`
- Center: `col-span-12 lg:col-span-6 xl:col-span-7`
- Right: `col-span-3`

**Responsive:**
- Mobile: Center column only (full width)
- Desktop: All three columns with sticky sidebars

**StatsPanel Contents:**
- CAL Energy bar with numeric display
- Current Rank badge
- This Week stats (Rides, Piles Found, Challenges)

**FeedPanel Contents:**
- Activity feed preview with "View All" link
- Leaderboard preview (top 3)
- Upcoming events card (purple CTA)

---

## Part 5: Errors Encountered & Resolutions

### 5.1 EmailStr Import Error

**Error:** `ImportError: email-validator is not installed`

**Cause:** Pydantic's EmailStr type requires optional dependency

**Fix:** Replaced with regex-based validation using `@field_validator`

### 5.2 Nested styled-jsx Error

**Error:** `Detected nested styled-jsx tag`

**Cause:** Mobile drawer had inline `<style jsx>` inside component that already had global styles

**Fix:** Moved animation keyframes to global styles block, used CSS class instead:
```typescript
// Before (nested - bad)
<div style={{ animation: 'slideInLeft 0.2s ease-out' }}>
  <style jsx>{`@keyframes slideInLeft {...}`}</style>

// After (class reference - good)
<div className="slide-in-left">
// In global styles: .slide-in-left { animation: slideInLeft 0.2s ease-out; }
```

### 5.3 SSH Connection Refused

**Error:** Intermittent SSH connection issues to DigitalOcean droplet

**Fix:** Wait 30 seconds and retry (transient network issue)

---

## Part 6: Design Philosophy Discussion

### The Ive Critique

A friend reviewed the product and provided feedback in Jony Ive's voice:

**On Error States:**
> "An error should feel like a soft landing, not a collision. The red triangle is harsh, alarmist."

**On Wallet Modal:**
> "The thick dashed container is playful but juvenile. The wallet is a trust moment. It deserves poise."

**On Profile Drawer:**
> "Identity is intimate. Handle it gently. The right panel's edge stroke is too bold, too comic."

**Overall Prescription:**
> "Technology dissolved until only intention remains."

### The Tension

| Ive Philosophy | Neo-Brutalist Philosophy |
|----------------|-------------------------|
| Technology dissolved | Technology celebrated |
| Whisper | Shout |
| Museum glass | Arcade cabinet |
| "Soft linen" | "Chunky plastic" |

### Resolution

**We kept neo-brutalism but cherry-picked valid UX principles:**

1. **Simplify during vulnerability** - Error/loading states should reduce visual noise
2. **Trust moments deserve calm** - Auth, payments, confirmations need less ink
3. **Copy as tone** - "Resume" > "Try Again", "Apply" > "Save Changes"
4. **Purpose-proportional presence** - No element louder than its job

**Key insight:** "Bold doesn't mean loud everywhere - it means intentional contrast. The quiet moments make the bold ones hit harder."

---

## Part 7: Files Modified

| File | Lines Changed | Description |
|------|--------------|-------------|
| `/backend/app/routes/waitlist.py` | +77 (new) | Public waitlist endpoint |
| `/backend/app/repositories.py` | +30 | `add_to_waitlist` method |
| `/backend/app/main.py` | +2 | Router registration |
| `/web/portal/src/app/page.tsx` | ~380 | Hybrid neo-brutalist styling |
| `/web/portal/src/app/app/layout.tsx` | ~365 | 3-column layout, StatsPanel, FeedPanel |
| `/web/portal/src/components/Header.tsx` | ~455 | Complete horizontal nav rewrite |
| `/web/portal/src/components/ProfilePanel.tsx` | +50 | Save button, handleSaveAll |

**Total:** ~1,200 lines changed

---

## Part 8: Testing Verification

| Feature | Test | Result |
|---------|------|--------|
| Waitlist | Submit email → check DB | ✅ Emails appear in `waitlist` table |
| Access Gate | Navigate to /app without invite | ✅ Redirects to landing |
| Access Gate | Navigate after invite code | ✅ Stays on /app |
| Save Button | Change profile → Save | ✅ Changes persist on reload |
| Contact Link | Click email link | ✅ Opens mail client |
| Build | `npm run build` | ✅ Passes |

---

## Part 9: Principles Crystallized

### For Future Design Work

1. **Simplify during vulnerability**
   - Error states, loading states, empty states should reduce noise
   - Hide what's not needed in these moments

2. **Trust moments deserve calm**
   - Authentication, payments, confirmations
   - Less ink, more breath
   - Action should feel inevitable, not sold

3. **Copy as tone**
   - "Resume" > "Try Again"
   - "Apply" > "Save Changes"
   - Language shapes how interaction *feels*

4. **Purpose-proportional presence**
   - No element louder than its job
   - A border exists to contain, not to announce

### Brand Guidelines Reinforced

- **"BOULDER ROLLER"** - no S! Not "Rollers"
- Keep neo-brutalist identity for differentiation
- Bold doesn't mean loud everywhere
- The beetle should feel like a beetle, not an Apple Pencil

---

## Part 10: Open Items / Future Work

1. **Tab Content Audit** - Some tabs may have lost content in previous context windows
2. **Mobile optimization** - 3-column collapses but could use refinement
3. **Apply Ive principles** - Error states could be calmer, wallet modal could be refined
4. **Real feed data** - Currently showing placeholder activity
5. **Leaderboard API** - Currently hardcoded top 3

---

## Appendix: Valid Invite Codes

```typescript
const VALID_CODES = ['alpha-code-1', 'alpha-code-2', 'alpha-code-3', 'dung', 'alpha-code-4'];
```

---

*Document generated: 2025-12-06*
*Session conducted with Claude Code (Opus 4.5)*
