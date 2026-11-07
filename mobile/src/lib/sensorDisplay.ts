import type {
  PowerSample,
  HeartRateSample,
  CadenceSample,
  SensorKind,
  SensorStatus,
} from '../services/sensors/types';

export const SENSOR_KIND_LABELS: Record<SensorKind, string> = {
  power: 'Power',
  heart_rate: 'Heart Rate',
  cadence: 'Cadence',
};

export const SENSOR_KIND_SHORT_LABELS: Record<SensorKind, string> = {
  power: 'Power',
  heart_rate: 'HR',
  cadence: 'Cadence',
};

export type SensorDisplayTone = 'ready' | 'working' | 'muted' | 'attention';

export interface SensorStatusDisplay {
  label: string;
  tone: SensorDisplayTone;
}

export interface SensorReadinessDisplay {
  label: string;
  detail: string;
  tone: SensorDisplayTone;
}

export interface LiveSensorDisplayItem {
  label: string;
  value: string;
  unit: string;
  state: 'live' | 'waiting' | 'missing';
}

export function kindsLine(kinds: SensorKind[], short = false): string {
  const labels = short ? SENSOR_KIND_SHORT_LABELS : SENSOR_KIND_LABELS;
  return kinds.map((k) => labels[k]).join(' · ');
}

export function displayForConnectionStatus(status?: SensorStatus): SensorStatusDisplay {
  switch (status) {
    case 'connected':
      return { label: 'Ready', tone: 'ready' };
    case 'connecting':
    case 'scanning':
      return { label: 'Connecting', tone: 'working' };
    case 'error':
      return { label: 'Needs attention', tone: 'attention' };
    case 'disconnected':
    default:
      return { label: 'Not nearby', tone: 'muted' };
  }
}

export function friendlyBleError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error ?? '');
  const normalized = message.toLowerCase();

  if (normalized.includes('permission') || normalized.includes('unauthorized')) {
    return 'Allow Bluetooth access in Settings, then try again.';
  }
  if (
    normalized.includes('powered off') ||
    normalized.includes('poweredoff') ||
    normalized.includes('bluetooth off') ||
    normalized.includes('not powered on')
  ) {
    return 'Turn on Bluetooth and keep the sensor awake, then try again.';
  }
  if (normalized.includes('timeout') || normalized.includes('timed out')) {
    return 'Wake the sensor and keep it close to your phone, then try again.';
  }
  if (
    normalized.includes('connection lost') ||
    normalized.includes('disconnected') ||
    normalized.includes('not in range')
  ) {
    return 'Keep the sensor awake and near your phone, then try again.';
  }
  return 'The sensor was not ready. Wake it up, keep it near your phone, and try again.';
}

export function buildSensorReadinessDisplay({
  connectedKinds,
  pairedCount,
  connectingCount = 0,
  attentionCount = 0,
}: {
  connectedKinds: SensorKind[];
  pairedCount: number;
  connectingCount?: number;
  attentionCount?: number;
}): SensorReadinessDisplay {
  if (connectedKinds.length > 0) {
    return {
      label: `${kindsLine(connectedKinds, true)} ready`,
      detail: `${connectedKinds.length} connected · ${pairedCount} paired`,
      tone: 'ready',
    };
  }
  if (connectingCount > 0) {
    return {
      label: 'Connecting sensors',
      detail: `${connectingCount} connecting · ${pairedCount} paired`,
      tone: 'working',
    };
  }
  if (attentionCount > 0) {
    return {
      label: 'Sensors need attention',
      detail: `${attentionCount} need attention · ${pairedCount} paired`,
      tone: 'attention',
    };
  }
  if (pairedCount > 0) {
    return {
      label: 'Sensors not nearby',
      detail: `${pairedCount} paired · rides use GPS only until they reconnect`,
      tone: 'muted',
    };
  }
  return {
    label: 'No sensors',
    detail: 'GPS-only ride',
    tone: 'muted',
  };
}

function liveValue(value: number | null | undefined): string {
  return Number.isFinite(value) ? Math.round(value as number).toString() : '--';
}

function liveState(
  canProvideValue: boolean,
  value: number | null | undefined,
): LiveSensorDisplayItem['state'] {
  if (Number.isFinite(value)) return 'live';
  return canProvideValue ? 'waiting' : 'missing';
}

export function buildLiveSensorDisplay({
  connectedKinds,
  power,
  heartRate,
  cadence,
}: {
  connectedKinds: SensorKind[];
  power: PowerSample | null;
  heartRate: HeartRateSample | null;
  cadence: CadenceSample | null;
}): LiveSensorDisplayItem[] {
  const connected = new Set(connectedKinds);
  return [
    {
      label: 'Power',
      value: liveValue(power?.power_w),
      unit: 'W',
      state: liveState(connected.has('power'), power?.power_w),
    },
    {
      label: 'Heart',
      value: liveValue(heartRate?.heart_rate_bpm),
      unit: 'bpm',
      state: liveState(connected.has('heart_rate'), heartRate?.heart_rate_bpm),
    },
    {
      label: 'Cadence',
      value: liveValue(cadence?.cadence_rpm),
      unit: 'rpm',
      state: liveState(
        connected.has('cadence') || connected.has('power'),
        cadence?.cadence_rpm,
      ),
    },
  ];
}
