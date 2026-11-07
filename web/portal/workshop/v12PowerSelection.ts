import type { PowerBest } from './v12Model';

export type PowerSelection = { band: [number, number]; index: number; effort: PowerBest };
// A duration band contains different best efforts. The release endpoint chooses
// one actual effort; neither band width nor a curve average is a ride interval.
export function selectPowerEffort(curve: PowerBest[], anchor: number, finish: number): PowerSelection | null {
  if (![anchor, finish].every(i => Number.isInteger(i) && i >= 0 && i < curve.length)) return null;
  return { band: [Math.min(anchor, finish), Math.max(anchor, finish)], index: finish, effort: curve[finish] };
}
