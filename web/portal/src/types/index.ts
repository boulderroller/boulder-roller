// User & Profile Types
export interface UserProfile {
  beetleId: number;
  username: string;
  walletAddress: string;
  weight: number; // in kg or lbs based on units preference
  riderType: RiderType;
  rank: BeetleRank;
  units: 'metric' | 'imperial';
  theme: ThemeId;
  createdAt: Date;
}

export type RiderType = 
  | 'sprinter' 
  | 'tt' 
  | 'climber' 
  | 'allrounder' 
  | 'diesel';

export type BeetleRank = 'A' | 'B' | 'C' | 'D' | 'E';

export type ThemeId = 
  | 'hoo-breddin' 
  | 'water' 
  | 'safari' 
  | 'honey' 
  | 'moss' 
  | 'foundries';

// Activity Types
export interface Activity {
  id: string;
  type: ActivityType;
  userId: string;
  username: string;
  action: string;
  timestamp: Date;
  dungEarned: number;
}

export type ActivityType = 'RIDE' | 'ACHIEVEMENT' | 'REWARD';

// Activity Feed Item (for display in feed)
export interface ActivityFeedItem {
  resultSummary?: import('../lib/api').FeedItemResultSummary | null;
  id: string;
  type: 'ride' | 'run';
  createdAt: string;
  title: string;
  date: string;
  distance: string;
  duration: string;
  elevation: string;
  avgPower?: string;
  location?: string;
  tss: number;
  dung: number;
  tokenAmountDisplay?: string;
  tokenLabel?: 'CAL' | 'DUNG';
  displayType: 'RIDE' | 'ACHIEVEMENT' | 'REWARD';
  user: string;
  handle?: string | null;
  avatarUrl?: string | null;
  riderPath?: string | null;
  action: string;
  time: string;
  dungDisplay: string;
  color: string;
  visualType?: 'image' | 'none';
  visualUrl?: string;
  mediaCount?: number;
  claps?: number;
  comments?: number;
  viewerHasKudos?: boolean;
  viewerReported?: boolean;
  reportStatus?: string | null;
  distanceM?: number | null;
  elevationM?: number | null;
  durationS?: number | null;
  calEarned?: number | null;
  isOwn?: boolean;
  placeLabel?: string | null;
  routePreview?: import('../lib/api').RoutePreview | null;
}

// Ride Types
export interface Ride {
  id: string;
  userId: string;
  name: string;
  date: Date;
  distance: number; // in meters
  duration: number; // in seconds
  elevation: number; // in meters
  tss: number; // Training Stress Score
  avgPower?: number; // watts
  normalizedPower?: number; // watts
  avgHeartRate?: number; // bpm
  // Token earnings
  dungEarned: number;
  calEarned?: number;
  fileUrl?: string; // GPX/FIT file
}

// Climb Types (canonical per PROTOCOL_TRUTHS §11)
export interface Climb {
  id: string;
  name: string;
  distance: number; // in meters
  elevation: number; // in meters
  grade: number; // average gradient percentage
  attempts: number;
  bestTime?: number; // in seconds
  bestPower?: number; // watts
}

// Stats Types
export interface UserStats {
  totalRides: number;
  totalDistance: number; // in meters
  totalElevation: number; // in meters
  totalTSS: number;
  totalDung: number;
  weeklyRides: number;
  weeklyTSS: number;
  weeklyDung: number;
}

// Energy System
export interface EnergyStatus {
  current: number;
  max: number;
  percentage: number;
  resetsAt: Date;
}

// Session Types
export interface UserSession {
  id: string;
  device: string;
  browser: string;
  location: string;
  lastActive: Date;
  isCurrent: boolean;
}

// Theme Types
export interface Theme {
  id: ThemeId;
  name: string;
  primaryColor: string;
  accentColor?: string;
}

// Invite Types
export interface Invite {
  code: string;
  createdBy: string;
  usedBy?: string;
  usedAt?: Date;
  expiresAt?: Date;
}
