# Profile Hub Implementation - Master Plan v2

> **Status**: Phase 1-3 Backend + iOS IMPLEMENTED (2024-12-03)

## Implementation Summary

### Completed Files

**Backend:**
- `backend/sql/009_user_profiles.sql` - Migration with username validation, reserved names, session metadata, user_stats view
- `backend/app/schemas.py` - Added 10+ new Pydantic models for profiles/sessions
- `backend/app/repositories.py` - Added 8 new repository methods
- `backend/app/routes/users.py` - Full CRUD for profiles + session management
- `backend/app/routes/rides.py` - Updated to use user's weight/FTP for calculations

**iOS:**
- `ios/BoulderRollers/Models/UserProfile.swift` - User models, session models
- `ios/BoulderRollers/Services/APIClient.swift` - Added profile/session API methods
- `ios/BoulderRollers/Views/Profile/ProfileView.swift` - Updated main profile view
- `ios/BoulderRollers/Views/Profile/EditProfileView.swift` - Edit profile with username check
- `ios/BoulderRollers/Views/Profile/SessionsView.swift` - Hyperliquid-style session management
- `ios/BoulderRollers/Views/Profile/FitnessSettingsView.swift` - Weight/FTP settings

---

## Executive Summary

Build a Hyperliquid-style Profile Hub that extends the existing SIWS auth system. The backend already has solid foundations (nonce TTL, refresh tokens, device binding). This plan adds:

1. **Extended user profiles** with fitness data for accurate TSS/kcal calculations
2. **Username system** with Web3 conventions (unique, lowercase, validated)
3. **Profile API** for viewing/editing
4. **Session management UI** (view devices, revoke sessions)
5. **Cross-platform consistency** (web + iOS)

---

## Phase 1: Database Schema Extension

### 1.1 Migration: `009_user_profiles.sql`

```sql
-- Extend users table with profile fields
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS username text UNIQUE,
  ADD COLUMN IF NOT EXISTS display_name text,
  ADD COLUMN IF NOT EXISTS bio text,
  ADD COLUMN IF NOT EXISTS avatar_url text,
  ADD COLUMN IF NOT EXISTS weight_kg numeric DEFAULT 75,
  ADD COLUMN IF NOT EXISTS ftp_w integer DEFAULT 200,
  ADD COLUMN IF NOT EXISTS preferred_units text DEFAULT 'metric' CHECK (preferred_units IN ('metric', 'imperial')),
  ADD COLUMN IF NOT EXISTS is_public boolean DEFAULT true,
  ADD COLUMN IF NOT EXISTS updated_at timestamptz DEFAULT now();

-- Username constraints
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_lower ON public.users(LOWER(username));

-- Username validation function
CREATE OR REPLACE FUNCTION validate_username(uname text) RETURNS boolean AS $$
BEGIN
  -- 3-20 chars, lowercase alphanumeric + underscores, must start with letter
  RETURN uname ~ '^[a-z][a-z0-9_]{2,19}$';
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Add check constraint
ALTER TABLE public.users
  ADD CONSTRAINT chk_username_valid CHECK (username IS NULL OR validate_username(username));

-- Reserved usernames (prevent impersonation)
CREATE TABLE IF NOT EXISTS public.reserved_usernames (
  username text PRIMARY KEY
);

INSERT INTO public.reserved_usernames (username) VALUES
  ('admin'), ('boulder'), ('rollers'), ('boulderrollers'),
  ('support'), ('help'), ('official'), ('mod'), ('moderator'),
  ('system'), ('api'), ('app'), ('web'), ('ios'), ('android')
ON CONFLICT DO NOTHING;

-- Function to check username availability
CREATE OR REPLACE FUNCTION is_username_available(uname text) RETURNS boolean AS $$
BEGIN
  IF NOT validate_username(uname) THEN
    RETURN false;
  END IF;
  IF EXISTS (SELECT 1 FROM public.reserved_usernames WHERE username = LOWER(uname)) THEN
    RETURN false;
  END IF;
  IF EXISTS (SELECT 1 FROM public.users WHERE LOWER(username) = LOWER(uname)) THEN
    RETURN false;
  END IF;
  RETURN true;
END;
$$ LANGUAGE plpgsql STABLE;

-- Add session metadata to refresh tokens
ALTER TABLE public.auth_refresh_tokens
  ADD COLUMN IF NOT EXISTS ip_address inet,
  ADD COLUMN IF NOT EXISTS location_hint text,
  ADD COLUMN IF NOT EXISTS last_used_at timestamptz;

-- Index for session listing
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_wallet_active
  ON public.auth_refresh_tokens(wallet)
  WHERE revoked_at IS NULL;

-- RLS: Users can only update their own profile
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

CREATE POLICY users_select_own ON public.users
  FOR SELECT USING (true); -- Public profiles readable by all

CREATE POLICY users_update_own ON public.users
  FOR UPDATE USING (auth.uid()::text = id::text);

-- Drop and recreate if needed (service role bypasses RLS)
DROP POLICY IF EXISTS users_service_all ON public.users;
```

### 1.2 Tasks

- [ ] Write migration file `backend/sql/009_user_profiles.sql`
- [ ] Test migration locally
- [ ] Apply to dev database
- [ ] Verify constraints work (try invalid usernames, duplicates)

---

## Phase 2: Backend API Extensions

### 2.1 Update Schemas (`backend/app/schemas.py`)

```python
# Add to existing schemas

class UsernameCheckRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=20)

class UsernameCheckResponse(BaseModel):
    available: bool
    reason: Optional[str] = None

class UserProfileUpdate(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=20)
    display_name: Optional[str] = Field(None, max_length=50)
    bio: Optional[str] = Field(None, max_length=280)
    avatar_url: Optional[HttpUrl] = None
    weight_kg: Optional[float] = Field(None, ge=30, le=300)
    ftp_w: Optional[int] = Field(None, ge=50, le=500)
    preferred_units: Optional[Literal['metric', 'imperial']] = None
    is_public: Optional[bool] = None

class UserProfilePublic(BaseModel):
    """Public profile view (for /users/{identifier})"""
    id: UUID
    wallet: str
    username: Optional[str]
    display_name: Optional[str]
    bio: Optional[str]
    avatar_url: Optional[str]
    is_public: bool
    created_at: Optional[datetime]
    # Stats (computed)
    total_rides: int = 0
    total_distance_km: float = 0
    total_elevation_m: float = 0
    total_dung_earned: int = 0

class UserProfilePrivate(UserProfilePublic):
    """Private profile view (for /users/me)"""
    email: Optional[str]
    weight_kg: float
    ftp_w: int
    preferred_units: str

class SessionInfo(BaseModel):
    id: UUID
    device_id: str
    user_agent: Optional[str]
    ip_address: Optional[str]
    location_hint: Optional[str]
    created_at: datetime
    last_used_at: Optional[datetime]
    is_current: bool = False

class SessionsListResponse(BaseModel):
    sessions: List[SessionInfo]
```

### 2.2 Repository Methods (`backend/app/repositories.py`)

```python
# Add to DatabaseRepository abstract class and SupabaseRepository

@abstractmethod
async def check_username_available(self, username: str) -> Tuple[bool, Optional[str]]: ...

@abstractmethod
async def update_user_profile(self, user_id: str, updates: Dict[str, Any]) -> Dict[str, Any]: ...

@abstractmethod
async def get_user_by_identifier(self, identifier: str) -> Optional[Dict[str, Any]]: ...
    """Get user by wallet address OR username"""

@abstractmethod
async def get_user_stats(self, user_id: str) -> Dict[str, Any]: ...
    """Aggregate stats: total rides, distance, elevation, dung"""

@abstractmethod
async def list_user_sessions(self, wallet: str) -> List[Dict[str, Any]]: ...

@abstractmethod
async def revoke_session(self, wallet: str, session_id: str) -> bool: ...

@abstractmethod
async def revoke_all_other_sessions(self, wallet: str, current_device_id: str) -> int: ...

@abstractmethod
async def update_session_last_used(self, token_hash: str) -> None: ...
```

### 2.3 New Routes (`backend/app/routes/users.py`)

```python
from fastapi import APIRouter, Depends, HTTPException, status
from ..dependencies import get_current_user, get_repository, AuthenticatedUser
from ..repositories import DatabaseRepository
from ..schemas import (
    UsernameCheckRequest, UsernameCheckResponse,
    UserProfileUpdate, UserProfilePublic, UserProfilePrivate,
    SessionInfo, SessionsListResponse
)

router = APIRouter()

@router.get("/me", response_model=UserProfilePrivate)
async def get_my_profile(
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
) -> UserProfilePrivate:
    """Get current user's full profile with private fields."""
    profile = await repo.get_user_profile(current_user.wallet)
    stats = await repo.get_user_stats(current_user.user_id)
    return UserProfilePrivate(**profile, **stats)

@router.put("/me", response_model=UserProfilePrivate)
async def update_my_profile(
    updates: UserProfileUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
) -> UserProfilePrivate:
    """Update current user's profile."""
    # Validate username if being changed
    if updates.username:
        available, reason = await repo.check_username_available(updates.username)
        if not available:
            raise HTTPException(status_code=400, detail=reason or "Username not available")

    updated = await repo.update_user_profile(
        current_user.user_id,
        updates.model_dump(exclude_unset=True)
    )
    stats = await repo.get_user_stats(current_user.user_id)
    return UserProfilePrivate(**updated, **stats)

@router.post("/check-username", response_model=UsernameCheckResponse)
async def check_username(
    request: UsernameCheckRequest,
    repo: DatabaseRepository = Depends(get_repository),
) -> UsernameCheckResponse:
    """Check if a username is available (public endpoint for UX)."""
    available, reason = await repo.check_username_available(request.username)
    return UsernameCheckResponse(available=available, reason=reason)

@router.get("/{identifier}", response_model=UserProfilePublic)
async def get_user_profile(
    identifier: str,
    repo: DatabaseRepository = Depends(get_repository),
) -> UserProfilePublic:
    """
    Get a user's public profile by wallet address or username.

    - Wallet: Full base58 address (e.g., "ABC123...")
    - Username: Prefixed with @ or just the username (e.g., "@alpha-code-3" or "alpha-code-3")
    """
    # Normalize: strip @ prefix if present
    lookup = identifier.lstrip("@")

    user = await repo.get_user_by_identifier(lookup)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.get("is_public", True):
        # Return minimal info for private profiles
        return UserProfilePublic(
            id=user["id"],
            wallet=user["wallet"][:8] + "...",
            username=user.get("username"),
            display_name=None,
            bio=None,
            avatar_url=None,
            is_public=False,
            created_at=None,
        )

    stats = await repo.get_user_stats(user["id"])
    return UserProfilePublic(**user, **stats)

# Session management
@router.get("/me/sessions", response_model=SessionsListResponse)
async def list_sessions(
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
) -> SessionsListResponse:
    """List all active sessions for the current user."""
    sessions = await repo.list_user_sessions(current_user.wallet)
    return SessionsListResponse(
        sessions=[
            SessionInfo(
                **s,
                is_current=(s["device_id"] == current_user.device_id)
            )
            for s in sessions
        ]
    )

@router.delete("/me/sessions/{session_id}")
async def revoke_session(
    session_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
) -> dict:
    """Revoke a specific session."""
    success = await repo.revoke_session(current_user.wallet, session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "revoked"}

@router.delete("/me/sessions")
async def revoke_all_other_sessions(
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
) -> dict:
    """Revoke all sessions except the current one."""
    count = await repo.revoke_all_other_sessions(
        current_user.wallet,
        current_user.device_id
    )
    return {"status": "revoked", "count": count}
```

### 2.4 Update Ride Metrics to Use User Profile

```python
# In backend/app/routes/rides.py, update the file upload endpoint:

@router.post("/upload/file", response_model=RideFileUploadResponse)
async def upload_ride_file(
    request: RideFileUploadRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    # Get user's fitness profile for accurate calculations
    profile = await repo.get_user_profile(current_user.wallet)
    user_weight_kg = profile.get("weight_kg", 75.0)
    user_ftp_w = profile.get("ftp_w", 200)

    # Parse and calculate with user-specific values
    parsed = parse_ride_file(request.file_data, request.file_type.value)
    metrics = calculate_metrics(parsed.records, user_weight_kg, user_ftp_w)

    # ... rest of endpoint
```

### 2.5 Tasks

- [ ] Add new schemas to `backend/app/schemas.py`
- [ ] Add repository methods to `backend/app/repositories.py`
- [ ] Create `backend/app/routes/users.py`
- [ ] Register router in `backend/app/main.py`
- [ ] Update rides endpoint to use user's weight/FTP
- [ ] Write tests for all new endpoints
- [ ] Test username validation edge cases

---

## Phase 3: iOS Implementation

### 3.1 Models (`ios/BoulderRollers/Models/`)

```swift
// User.swift
struct UserProfile: Codable, Identifiable {
    let id: UUID
    let wallet: String
    var username: String?
    var displayName: String?
    var bio: String?
    var avatarUrl: String?
    var weightKg: Double
    var ftpW: Int
    var preferredUnits: PreferredUnits
    var isPublic: Bool
    let createdAt: Date?

    // Stats
    var totalRides: Int
    var totalDistanceKm: Double
    var totalElevationM: Double
    var totalDungEarned: Int

    enum PreferredUnits: String, Codable {
        case metric, imperial
    }
}

struct UserProfileUpdate: Codable {
    var username: String?
    var displayName: String?
    var bio: String?
    var avatarUrl: String?
    var weightKg: Double?
    var ftpW: Int?
    var preferredUnits: String?
    var isPublic: Bool?
}

struct SessionInfo: Codable, Identifiable {
    let id: UUID
    let deviceId: String
    let userAgent: String?
    let ipAddress: String?
    let locationHint: String?
    let createdAt: Date
    let lastUsedAt: Date?
    let isCurrent: Bool
}
```

### 3.2 APIClient Extensions

```swift
// Add to APIClient.swift

// MARK: - User Profile

func getMyProfile() async throws -> UserProfile {
    try await get("/users/me")
}

func updateMyProfile(_ updates: UserProfileUpdate) async throws -> UserProfile {
    try await put("/users/me", body: updates)
}

func checkUsername(_ username: String) async throws -> UsernameCheckResponse {
    try await post("/users/check-username", body: ["username": username])
}

func getUserProfile(identifier: String) async throws -> UserProfile {
    try await get("/users/\(identifier)")
}

// MARK: - Sessions

func listSessions() async throws -> [SessionInfo] {
    struct Response: Codable { let sessions: [SessionInfo] }
    let response: Response = try await get("/users/me/sessions")
    return response.sessions
}

func revokeSession(id: UUID) async throws {
    try await delete("/users/me/sessions/\(id)")
}

func revokeAllOtherSessions() async throws -> Int {
    struct Response: Codable { let count: Int }
    let response: Response = try await delete("/users/me/sessions")
    return response.count
}
```

### 3.3 Views

```
ios/BoulderRollers/Views/Profile/
├── ProfileView.swift           # Main profile tab
├── EditProfileView.swift       # Edit profile form
├── UsernameSetupView.swift     # First-time username picker
├── FitnessSettingsView.swift   # Weight/FTP settings
├── SessionsView.swift          # Manage active sessions
└── PublicProfileView.swift     # View other users' profiles
```

### 3.4 Key UI Components

**ProfileView.swift** - Main profile display:
- Avatar (tap to change)
- Username / display name
- Bio
- Stats cards (rides, distance, elevation, DUNG)
- Edit button → EditProfileView
- Settings gear → SettingsView

**EditProfileView.swift**:
- Username field with real-time availability check
- Display name
- Bio (280 char limit with counter)
- Avatar URL (or photo picker for future)
- Save/Cancel buttons

**FitnessSettingsView.swift**:
- Weight (kg/lbs based on preferred_units)
- FTP
- Explanation of why this matters for TSS

**SessionsView.swift**:
- List of active sessions with device info
- Current session highlighted
- "Revoke" button per session
- "Log out everywhere else" button

### 3.5 Tasks

- [ ] Create `Models/User.swift`
- [ ] Add API methods to `APIClient.swift`
- [ ] Create `Views/Profile/ProfileView.swift`
- [ ] Create `Views/Profile/EditProfileView.swift`
- [ ] Create `Views/Profile/UsernameSetupView.swift`
- [ ] Create `Views/Profile/FitnessSettingsView.swift`
- [ ] Create `Views/Profile/SessionsView.swift`
- [ ] Add Profile tab to MainTabView
- [ ] Handle first-login username prompt
- [ ] Test on device

---

## Phase 4: Web Portal (Future)

### 4.1 Setup
- [ ] Install `@solana/wallet-adapter-*`
- [ ] Configure WalletProvider

### 4.2 Auth Flow
- [ ] ConnectWalletButton component
- [ ] Challenge → Sign → Login flow
- [ ] HttpOnly cookie session

### 4.3 Profile UI
- [ ] /profile page
- [ ] Edit profile modal
- [ ] Sessions management

---

## Phase 5: Testing & Hardening

### 5.1 Backend Tests
- [ ] Username validation (valid, invalid, reserved, duplicate)
- [ ] Profile update (partial updates, full updates)
- [ ] Session management (list, revoke, revoke all)
- [ ] Public profile access control (public vs private)
- [ ] Rate limiting on username check endpoint

### 5.2 E2E Tests
- [ ] Full signup flow: Connect → Login → Set username
- [ ] Profile edit round-trip
- [ ] Cross-platform consistency (edit on iOS, verify on web)
- [ ] Session revocation (revoke on web, verify iOS gets 401)

### 5.3 Security Checklist
- [ ] Username enumeration protection (rate limit check endpoint)
- [ ] SQL injection on identifier lookup
- [ ] XSS on bio/display_name fields
- [ ] CSRF on profile update (if web uses cookies)
- [ ] Token refresh updates `last_used_at`

---

## Migration Checklist

1. **Pre-deploy**
   - [ ] Backup production database
   - [ ] Test migration on staging

2. **Deploy**
   - [ ] Run migration `009_user_profiles.sql`
   - [ ] Deploy backend
   - [ ] Deploy iOS (via TestFlight)

3. **Post-deploy**
   - [ ] Verify existing users can access profiles
   - [ ] Test new user signup
   - [ ] Monitor error logs

---

## API Reference (Quick)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/users/me` | Yes | Get my full profile |
| PUT | `/users/me` | Yes | Update my profile |
| POST | `/users/check-username` | No | Check username availability |
| GET | `/users/{identifier}` | No | Get public profile by wallet/@username |
| GET | `/users/me/sessions` | Yes | List my active sessions |
| DELETE | `/users/me/sessions/{id}` | Yes | Revoke specific session |
| DELETE | `/users/me/sessions` | Yes | Revoke all other sessions |

---

## Notes

- **Weight/FTP**: Critical for accurate TSS/kcal. Prompt users to set these during onboarding.
- **Username vs Wallet**: Users can be looked up by either. Usernames are optional but encouraged.
- **Private profiles**: Hide stats and bio, show minimal info. Still allow wallet lookup for token transfers.
- **Session management**: Hyperliquid-style "see where you're logged in" is a trust signal.
