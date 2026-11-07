# Web Portal Audit - Fix Instructions

## Overview
This document contains all flagged issues from the web portal audit with detailed fix instructions. Portal is React/TypeScript.

**Base Path:** `/Users/gabetemp/curahee/BoulderRollers-v2/web/portal`

---

## CRITICAL PRIORITY

### 1. CreatePileModal is Completely Stubbed
**File:** `web/portal/src/components/CreatePileModal.tsx:42-46`
**Current State:** Just renders placeholder text, no functionality

**Solution:**
Implement full pile creation flow:

```typescript
// CreatePileModal.tsx
import { useState, useRef } from 'react';
import mapboxgl from 'mapbox-gl';
import MapboxDraw from '@mapbox/mapbox-gl-draw';

interface CreatePileModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated: (pile: Pile) => void;
}

export function CreatePileModal({ isOpen, onClose, onCreated }: CreatePileModalProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [coordinates, setCoordinates] = useState<[number, number][]>([]);
  const [isDrawing, setIsDrawing] = useState(false);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const drawRef = useRef<MapboxDraw | null>(null);

  const handleMapLoad = (map: mapboxgl.Map) => {
    mapRef.current = map;

    // Add draw control
    const draw = new MapboxDraw({
      displayControlsDefault: false,
      controls: { polygon: true, trash: true }
    });
    map.addControl(draw);
    drawRef.current = draw;

    map.on('draw.create', (e) => {
      const coords = e.features[0].geometry.coordinates[0];
      setCoordinates(coords);
    });
  };

  const handleSubmit = async () => {
    if (!name || coordinates.length < 3) return;

    const pile = await api.createPile({
      name,
      description,
      boundaries: coordinates
    });

    onCreated(pile);
    onClose();
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose}>
      <div className="space-y-4">
        <input
          placeholder="Pile name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <textarea
          placeholder="Description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <div className="h-64">
          <Map onLoad={handleMapLoad} />
        </div>
        <p className="text-sm text-gray-500">
          {coordinates.length > 0
            ? `${coordinates.length} points selected`
            : 'Draw a polygon on the map to define pile boundaries'}
        </p>
        <button onClick={handleSubmit} disabled={!name || coordinates.length < 3}>
          Create Pile
        </button>
      </div>
    </Modal>
  );
}
```

**Dependencies to add:**
```bash
npm install @mapbox/mapbox-gl-draw
```

---

### 2. uploadRide Function is No-Op
**File:** `web/portal/src/contexts/AppContext.tsx:179-182`
**Current State:**
```typescript
const uploadRide = async (rideData: RideData) => {
  // placeholder: backend returns rides immediately after upload via invalidation
};
```

**Solution:**
```typescript
const uploadRide = async (file: File) => {
  setIsUploading(true);
  try {
    const formData = new FormData();
    formData.append('file', file);

    const response = await api.uploadRide(formData);

    // Refresh rides list
    await fetchRides();

    return response;
  } catch (error) {
    console.error('Upload failed:', error);
    throw error;
  } finally {
    setIsUploading(false);
  }
};
```

Also need to add API method in `lib/api.ts`:
```typescript
async uploadRide(formData: FormData): Promise<RideUploadResponse> {
  const response = await fetch(`${this.baseUrl}/rides/upload`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${this.getToken()}`
    },
    body: formData
  });

  if (!response.ok) throw new Error('Upload failed');
  return response.json();
}
```

---

### 3. "YOUR PILES" Always Returns Empty
**File:** `web/portal/src/components/PilesTab.tsx:12-15`
**Current State:**
```typescript
const displayedPiles = view === 'yours' ? [] : piles;
```

**Solution:**
```typescript
const [userPiles, setUserPiles] = useState<Pile[]>([]);

useEffect(() => {
  if (view === 'yours') {
    api.getMyPiles().then(setUserPiles);
  }
}, [view]);

const displayedPiles = view === 'yours' ? userPiles : piles;
```

Add API method:
```typescript
async getMyPiles(): Promise<Pile[]> {
  return this.get('/piles/mine');
}
```

---

## HIGH PRIORITY

### 4. FeedTab is Placeholder
**File:** `web/portal/src/components/FeedTab.tsx:6`
**Current:** Shows "coming soon"

**Solution:**
```typescript
export function FeedTab() {
  const [activities, setActivities] = useState<Activity[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getFeed()
      .then(setActivities)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <LoadingSpinner />;

  return (
    <div className="space-y-4">
      {activities.map((activity) => (
        <ActivityCard key={activity.id} activity={activity} />
      ))}
      {activities.length === 0 && (
        <p className="text-center text-gray-500">
          No activity yet. Follow some riders to see their rides here!
        </p>
      )}
    </div>
  );
}

function ActivityCard({ activity }: { activity: Activity }) {
  return (
    <div className="border rounded-lg p-4">
      <div className="flex items-center gap-2 mb-2">
        <Avatar user={activity.user} />
        <span className="font-medium">{activity.user.displayName}</span>
        <span className="text-gray-500 text-sm">{formatTimeAgo(activity.createdAt)}</span>
      </div>
      <p>{activity.type === 'ride' ? `Completed a ${activity.distance}km ride` : activity.message}</p>
    </div>
  );
}
```

---

### 5. MapView Uses Fake Markers
**File:** `web/portal/src/components/MapView.tsx:24`
**Current:** Placeholder markers at computed positions

**Solution:**
Replace with real Mapbox integration:
```typescript
import mapboxgl from 'mapbox-gl';
import 'mapbox-gl/dist/mapbox-gl.css';

export function MapView({ piles }: { piles: Pile[] }) {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<mapboxgl.Map | null>(null);

  useEffect(() => {
    if (!mapContainer.current) return;

    mapboxgl.accessToken = process.env.NEXT_PUBLIC_MAPBOX_TOKEN!;

    map.current = new mapboxgl.Map({
      container: mapContainer.current,
      style: 'mapbox://styles/mapbox/outdoors-v12',
      center: [-105.2705, 40.0150], // Boulder, CO
      zoom: 10
    });

    return () => map.current?.remove();
  }, []);

  useEffect(() => {
    if (!map.current) return;

    // Add pile markers
    piles.forEach((pile) => {
      new mapboxgl.Marker()
        .setLngLat([pile.centerLon, pile.centerLat])
        .setPopup(new mapboxgl.Popup().setHTML(`
          <h3>${pile.name}</h3>
          <p>${pile.totalStaked} DUNG staked</p>
        `))
        .addTo(map.current!);
    });
  }, [piles]);

  return <div ref={mapContainer} className="w-full h-full" />;
}
```

---

### 6. No File Parsing in RideUploadModal
**File:** `web/portal/src/components/RideUploadModal.tsx:19-22`
**Current:** Fake 1500ms delay, no actual parsing

**Solution:**
For MVP, just upload the file to backend (backend will parse):
```typescript
const handleUpload = async () => {
  if (!selectedFile) return;

  setIsProcessing(true);
  try {
    const result = await uploadRide(selectedFile);
    setUploadedRide(result);
    onSuccess(result);
  } catch (error) {
    setError('Upload failed. Please try again.');
  } finally {
    setIsProcessing(false);
  }
};
```

For client-side preview (optional enhancement), use:
- `fit-file-parser` npm package for .FIT files
- Native DOMParser for GPX/TCX (XML)

---

### 7. Mock Recent Rides in ProfileTab
**File:** `web/portal/src/components/ProfileTab.tsx:37-59`
**Current:** Hardcoded array

**Solution:**
```typescript
const [rides, setRides] = useState<Ride[]>([]);
const [loading, setLoading] = useState(true);

useEffect(() => {
  api.getMyRides({ limit: 5 })
    .then(setRides)
    .finally(() => setLoading(false));
}, []);
```

---

### 8. Mock Governance Proposals
**File:** `web/portal/src/components/GovernanceTab.tsx:17-36`

**Solution:**
```typescript
const [proposals, setProposals] = useState<Proposal[]>([]);

useEffect(() => {
  api.getProposals().then(setProposals);
}, []);

const handleVote = async (proposalId: string, vote: 'for' | 'against') => {
  await api.vote(proposalId, vote);
  // Refresh proposals
  const updated = await api.getProposals();
  setProposals(updated);
};
```

**Note:** Requires backend governance endpoints to be implemented first.

---

### 9. Mock Trading Pairs & No Swap
**File:** `web/portal/src/components/TradingTab.tsx:9-74`

**Solution:**
For MVP, show real token balances and link to external DEX:
```typescript
const [balances, setBalances] = useState({ dung: 0, kcal: 0 });

useEffect(() => {
  api.getTokenBalances().then(setBalances);
}, []);

const handleSwap = () => {
  // Link to Raydium/Jupiter for actual swaps
  window.open('https://jup.ag/swap/DUNG-SOL', '_blank');
};
```

---

### 10. Zero Yield Always
**File:** `web/portal/src/components/PortfolioTab.tsx:12-13`
**Current:** `const totalYield = 0;`

**Solution:**
```typescript
const [portfolio, setPortfolio] = useState({
  totalStaked: 0,
  totalYield: 0,
  claims: []
});

useEffect(() => {
  api.getPortfolio().then(setPortfolio);
}, []);

// Calculate yield from claims
const totalYield = portfolio.claims.reduce(
  (sum, claim) => sum + (claim.earnedDung || 0),
  0
);
```

---

## MEDIUM PRIORITY

### 11. Mock Following List
**File:** `web/portal/src/components/FollowingModal.tsx:21-24`

```typescript
const [users, setUsers] = useState<User[]>([]);

useEffect(() => {
  const fetchUsers = type === 'following'
    ? api.getFollowing(userId)
    : api.getFollowers(userId);
  fetchUsers.then(setUsers);
}, [type, userId]);
```

---

### 12. Mock Achievements
**File:** `web/portal/src/components/AchievementsTab.tsx:7-10`

```typescript
const [achievements, setAchievements] = useState<Achievement[]>([]);

useEffect(() => {
  api.getAchievements().then(setAchievements);
}, []);
```

---

### 13. Random Stats Data
**File:** `web/portal/src/components/StatsTab.tsx:5-9`

```typescript
const [weeklyData, setWeeklyData] = useState<WeeklyStats[]>([]);

useEffect(() => {
  api.getWeeklyStats().then(setWeeklyData);
}, []);
```

---

### 14. Mock Swanny Data
**File:** `web/portal/src/components/SwannyTab.tsx:7-12`

```typescript
const [swannyData, setSwannyData] = useState<SwannyData | null>(null);

useEffect(() => {
  api.getSwannyData().then(setSwannyData);
}, []);
```

---

## API Methods Needed

Add these to `lib/api.ts`:
```typescript
// Piles
getMyPiles(): Promise<Pile[]>
createPile(data: CreatePileInput): Promise<Pile>

// Feed
getFeed(): Promise<Activity[]>

// Rides
uploadRide(formData: FormData): Promise<RideUploadResponse>
getMyRides(options?: { limit?: number }): Promise<Ride[]>

// Governance
getProposals(): Promise<Proposal[]>
vote(proposalId: string, vote: 'for' | 'against'): Promise<void>

// Portfolio
getPortfolio(): Promise<Portfolio>
getTokenBalances(): Promise<{ dung: number; kcal: number }>

// Social
getFollowing(userId: string): Promise<User[]>
getFollowers(userId: string): Promise<User[]>

// Stats
getWeeklyStats(): Promise<WeeklyStats[]>
getAchievements(): Promise<Achievement[]>
getSwannyData(): Promise<SwannyData>
```

---

## Testing Checklist
- [ ] Can create a pile with map drawing
- [ ] Can upload a ride file
- [ ] "Your Piles" shows user's piles
- [ ] Feed shows activity from followed users
- [ ] Map shows real pile locations
- [ ] Profile shows real recent rides
- [ ] No mock/random data in any component
- [ ] All API calls have error handling
- [ ] Loading states show spinners
