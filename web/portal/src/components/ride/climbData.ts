export interface ClimbData {
  id?: string;
  objectClimbId?: string;
  name?: string;
  distanceM: number;
  elevationM: number;
  avgGradient: number;
  category?: string | null;
  timeS: number;
  avgSpeedKmh?: number;
  vam?: number;
  dungEarned?: number;
  vaultMatched?: boolean;
  startIndex?: number;
  endIndex?: number;
  startOffsetS?: number;
  endOffsetS?: number;
  // Extended data for vault creation
  signatureHex?: string;
  roadName?: string;
  tileCount?: number;
  // Real completion-backed facts from the ride patterns endpoint; present
  // only when this ride produced an authoritative vault completion.
  vaultMatch?: {
    vaultId: number;
    vaultClimbId?: string | null;
    name?: string | null;
    yourTime?: number | null;
    yourRank?: number | null;
    yourBestTime?: number | null;
    isPR?: boolean | null;
    komTime?: number | null;
    komHolder?: string | null;
  };
}
