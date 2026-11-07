import { nearestIndex, type AnalysisSample, type Axis, type SampleRange } from './v3Model';

export function boundSelection(subject: SampleRange, a: number, b: number): SampleRange {
  const clamp = (n: number) => Math.max(subject.startIndex, Math.min(subject.endIndex, Math.round(n)));
  let startIndex = clamp(Math.min(a, b)), endIndex = clamp(Math.max(a, b));
  if (startIndex === endIndex) {
    if (endIndex < subject.endIndex) endIndex++;
    else startIndex = Math.max(subject.startIndex, endIndex - 1);
  }
  return { startIndex, endIndex };
}

export function resizeSelection(subject: SampleRange, selection: SampleRange, edge: 'start' | 'end', index: number): SampleRange {
  return edge === 'start'
    ? { startIndex: Math.max(subject.startIndex, Math.min(selection.endIndex - 1, Math.round(index))), endIndex: selection.endIndex }
    : { startIndex: selection.startIndex, endIndex: Math.min(subject.endIndex, Math.max(selection.startIndex + 1, Math.round(index))) };
}

/** Translation follows physical distance/time, clamped before snapping to recorded samples. */
export function translateSelection(samples: AnalysisSample[], subject: SampleRange, selection: SampleRange, delta: number, axis: Axis): SampleRange {
  const key = axis === 'time' ? 't' : 'd';
  const first = samples[selection.startIndex][key], last = samples[selection.endIndex][key];
  const shift = Math.max(samples[subject.startIndex][key] - first, Math.min(samples[subject.endIndex][key] - last, delta));
  // Distance cannot distinguish samples within a stationary interval. Use time to move it.
  if (shift === 0 || (axis === 'distance' && first === last)) return selection;
  return boundSelection(subject, nearestIndex(samples, first + shift, axis), nearestIndex(samples, last + shift, axis));
}
