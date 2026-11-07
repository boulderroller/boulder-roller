import type { ClimbPowerFields } from '../../lib/api';
import { formatWatts, formatWattsPerKilogram } from '../../lib/formatters';
import { EstimatedValue } from '../EstimatedValue';

export function climbPowerValue(power: ClimbPowerFields): number | null {
  const value = power.powerKind === 'measured' ? power.avgPowerW
    : power.powerKind === 'estimated' ? power.estimatedPowerW : null;
  return value != null && Number.isFinite(value) && value >= 0 ? value : null;
}

/** W/kg is a viewer-filtered API value. This component never derives it. */
export function ClimbPower({ power }: { power: ClimbPowerFields }) {
  const value = climbPowerValue(power);
  if (value === null) return null;
  return <span className="climb-power">
    {power.powerKind === 'estimated'
      ? <EstimatedValue measurement={{ value, estimate: true, range: power.estimatedPowerRangeW }} formatValue={formatWatts} align="end" openOnFocus />
      : <span><span aria-hidden="true">⚡ </span>{formatWatts(value)}</span>}
    {power.wPerKg != null && Number.isFinite(power.wPerKg) && power.wPerKg >= 0
      ? <span className="climb-power__wkg">{formatWattsPerKilogram(power.wPerKg)}</span> : null}
  </span>;
}
