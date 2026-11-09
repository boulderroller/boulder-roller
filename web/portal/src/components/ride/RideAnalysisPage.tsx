import { ridePresentationFacts, formatRidePresentation } from '../../../server/ride-card-shape';
import '../../styles/portal-ride-analysis.css';
import { useEffect, useMemo, useRef, useState, type PointerEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, type Ride, type PowerCurve } from '../../lib/api';
import { EstimatedValue } from '../EstimatedValue';
import { trainingRead } from './trainingRead';
import { useFormatters } from '../../hooks/useFormatters';
import {
  ABSENT_VALUE,
  formatInteger,
  formatFixed,
  formatWatts,
  formatCadence,
  formatDurationCompact,
  formatHoursMinutes,
  formatPercent,
  formatSpeedKmh,
  formatMeters,
} from '../../lib/formatters';
import {
  finite,
  nearest,
  pathFor,
  instrumentSamples,
  type RideSample,
  type RideSpan,
  type TimedValue,
} from './ridePageModel';
export type RidePageModel = {
  samples: RideSample[];
  spans: RideSpan[];
  streams: Record<'power' | 'cadence' | 'speed' | 'heartRate', TimedValue[]>;
};
const mono = (value: number | null, unit = '') =>
  value === null || !finite(value) ? '' : unit === 'W'
    ? formatWatts(value)
    : unit === 'rpm'
      ? formatCadence(value)
      : value === null
        ? ABSENT_VALUE
        : formatInteger(value);
function Words({
  values,
  current,
  onChange,
  label,
}: {
  values: { id: string; name: string }[];
  current: string;
  onChange: (id: string) => void;
  label: string;
}) {
  return (
    <div className="ride-words" role="group" aria-label={label}>
      {values.map((v) => (
        <button
          key={v.id}
          aria-pressed={current === v.id}
          onClick={() => onChange(v.id)}
        >
          {v.name}
        </button>
      ))}
    </div>
  );
}
export default function RideAnalysisPage({
  ride,
  model,
  isOwner,
  ownerId,
  title,
  rider,
  date,
  estimated = false,
  formatReadout,
}: {
  ride: Ride;
  model: RidePageModel;
  isOwner: boolean;
  ownerId: string | null;
  title: string;
  rider: string;
  date: string;
  estimated?: boolean;
  formatReadout: (sample: RideSample | undefined) => Record<string, string>;
}) {
  const f = useFormatters(),
    navigate = useNavigate(),
    { climbId } = useParams();
  const { samples, spans, streams } = model;
  const [axis, setAxis] = useState('distance'),
    [range, setRange] = useState<[number, number] | null>(null),
    [dragging, setDragging] = useState(false),
    [scrub, setScrub] = useState(0),
    [width, setWidth] = useState(1080),
    [curveWidth, setCurveWidth] = useState(480),
    [rangeAnchor, setRangeAnchor] = useState<number | null>(null);
  const curveRef = useRef<HTMLDivElement>(null);
  const ref = useRef<HTMLDivElement>(null),
    drag = useRef<{ index: number; x: number } | null>(null);
  const best = useQuery<PowerCurve>({
    queryKey: ['ride-page', 'power-curve', ownerId],
    queryFn: () => api.getPowerCurve(),
    enabled: isOwner && Boolean(ownerId) && !estimated,
    retry: false,
    staleTime: 60_000,
  });
  const scope = spans.find((s) => s.id === climbId);
  const scopeSamples = useMemo(
    () =>
      scope
        ? samples.filter((p) => p.t >= scope.start && p.t <= scope.end)
        : samples,
    [samples, scope],
  );
  const presentationFacts = ridePresentationFacts(ride, ride.id, isOwner ? 'owner' : 'public');
  const sourceReduction = presentationFacts.presentation?.traceReduction;
  const figure = useMemo(
    () => instrumentSamples(scopeSamples, Boolean(scope), sourceReduction),
    [scopeSamples, scope, sourceReduction],
  );
  const figureSamples = figure.samples;
  useEffect(() => {
    setRange(null);
    setRangeAnchor(null);
    setScrub(0);
  }, [climbId, ride.id]);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const style = getComputedStyle(el);
      setWidth(
        el.clientWidth -
          parseFloat(style.paddingLeft) -
          parseFloat(style.paddingRight),
      );
    };
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    measure();
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const el = curveRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setCurveWidth(entry.contentRect.width));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const chosen = range
    ? scopeSamples.slice(range[0], range[1] + 1)
    : scopeSamples;
  const from = chosen[0]?.t ?? scope?.start ?? 0,
    to = chosen.at(-1)?.t ?? scope?.end ?? ride.durationS ?? 0;
  const spanTraining = useQuery({
    queryKey: ['ride-training', ride.id, scope?.id, range ? from : null, range ? to : null],
    queryFn: () => api.getRideTraining(ride.id, from, to),
    enabled: isOwner && !dragging && Boolean(scope || range) && to > from,
    retry: false,
    staleTime: 60_000,
  });
  const training = scope || range ? spanTraining.data : ride.trainingMetrics;
  const threshold = training?.threshold?.value ?? null;
  const read = trainingRead(training);
  const summary = useMemo(() => {
    const partial = !!scope || !!range;
    return {
      distance: training?.distanceM ?? (partial ? null : presentationFacts.distanceM),
      elevation: training?.elevationGainM ?? (partial ? null : presentationFacts.elevationM),
      time: training?.elapsedS ?? (partial ? null : presentationFacts.durationS),
      power: training?.avgPowerW ?? null,
    };
  }, [training, scope, range, presentationFacts.distanceM, presentationFacts.elevationM, presentationFacts.durationS]);
  const summaryText = formatRidePresentation({ distanceM: summary.distance, elevationM: summary.elevation, durationS: summary.time }, f);
  const curveDurations = (read.durations.length ? read.durations : best.data?.durationsS ?? []).filter(d => d >= 5);
  const curve = curveDurations.map(d => {
    const index = read.durations.indexOf(d);
    return index < 0 ? null : read.curve[index] ?? null;
  });
  const zones = read.zones;
  const zoneDenominator = zones?.total ? { durationS: zones.total } : null;
  const moving = read.moving;
  const maximum = training?.maxPowerW ?? null;
  const changeScope = (id: string) => {
    setRange(null);
    navigate(
      id === 'whole'
        ? `/activities/${ride.id}/analysis`
        : `/activities/${ride.id}/climbs/${encodeURIComponent(id)}/analysis`,
    );
  };
  const phone = width < 600,
    left = phone ? 52 : 76,
    right = phone ? 10 : 16,
    plotW = Math.max(1, width - left - right),
    axisValue = (p: RideSample) => (axis === 'time' ? p.t : p.d);
  const minX = scopeSamples.length ? axisValue(scopeSamples[0]) : 0,
    maxX = scopeSamples.length ? axisValue(scopeSamples.at(-1)!) : 1,
    extent = Math.max(1, maxX - minX);
  const x = (p: RideSample) => left + ((axisValue(p) - minX) / extent) * plotW;
  const unit = axis === 'time' ? '' : extent < 3000 ? 'M' : 'KM';
  const labelX = (v: number) =>
    axis === 'time'
      ? f.duration(v - minX)
      : formatFixed(
          (v - minX) / (unit === 'M' ? 1 : 1000),
          unit === 'M' ? 0 : 1,
        );
  const baseMajor =
    axis === 'time'
      ? extent > 7200
        ? 1800
        : extent > 1800
          ? 600
          : extent > 300
            ? 60
            : 30
      : scope
        ? extent > 1000
          ? 250
          : 100
        : extent > 30000
          ? phone
            ? 20000
            : 10000
          : extent > 10000
            ? 2000
            : 1000;
  const major = baseMajor * Math.max(1, Math.ceil((extent / baseMajor) / Math.max(1, Math.floor(plotW / 90))));
  const minor = major / (scope ? 5 : 2);
  const ticks = Array.from(
    { length: Math.floor(extent / minor) + 1 },
    (_, i) => ({
      value: i * minor,
      major:
        Math.abs((i * minor) / major - Math.round((i * minor) / major)) < 1e-6,
    }),
  );
  const indexAt = (e: PointerEvent<SVGSVGElement>) => {
    const b = e.currentTarget.getBoundingClientRect();
    return nearest(
      scopeSamples,
      minX +
        Math.max(
          0,
          Math.min(1, (e.clientX - b.left - left) / (b.width - left - right)),
        ) *
          extent,
      axisValue,
    );
  };
  const active = scopeSamples[Math.min(scrub, scopeSamples.length - 1)];
  const activeFigure = active
    ? figureSamples[nearest(figureSamples, axisValue(active), axisValue)]
    : undefined;
  const selectKeyboardRange = () => {
    if (rangeAnchor === null) {
      setRangeAnchor(scrub);
      setRange(null);
    } else {
      setRange([Math.min(rangeAnchor, scrub), Math.max(rangeAnchor, scrub)]);
      setRangeAnchor(null);
    }
  };
  const rows = [
    {
      key: 'elevation',
      name: 'Elevation',
      unit: 'M',
      height: phone ? 100 : 132,
      step: scope ? 20 : 50,
    },
    {
      key: 'power',
      name: 'Power',
      unit: 'W',
      height: phone ? 124 : 172,
      step: 100,
    },
    {
      key: 'cadence',
      name: 'Cadence',
      unit: 'RPM',
      height: phone ? 66 : 92,
      step: 40,
    },
    {
      key: 'speed',
      name: 'Speed',
      unit: 'KM/H',
      height: phone ? 66 : 92,
      step: 20,
    },
    ...(streams.heartRate.length
      ? [
          {
            key: 'heartRate',
            name: 'Heart rate',
            unit: 'BPM',
            height: phone ? 66 : 92,
            step: 50,
          },
        ]
      : []),
  ];
  const pointerDown = (e: PointerEvent<SVGSVGElement>) => {
    if (e.button !== 0 || !scopeSamples.length) return;
    const index = indexAt(e);
    drag.current = { index, x: e.clientX };
    setDragging(true);
    setScrub(index);
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const pointerMove = (e: PointerEvent<SVGSVGElement>) => {
    const index = indexAt(e);
    setScrub(index);
    if (drag.current && Math.abs(e.clientX - drag.current.x) > 5)
      setRange([
        Math.min(index, drag.current.index),
        Math.max(index, drag.current.index),
      ]);
  };
  const pointerUp = (e: PointerEvent<SVGSVGElement>) => {
    const d = drag.current;
    drag.current = null;
    setDragging(false);
    if (!d) return;
    if (Math.abs(e.clientX - d.x) <= 5 && !scope) {
      const t = scopeSamples[indexAt(e)]?.t,
        span = spans.find((s) => t >= s.start && t <= s.end);
      if (span) changeScope(span.id);
    }
  };
  const bestAt = (duration: number) => {
    if (!isOwner || !best.data?.available) return null;
    const i = best.data.durationsS.indexOf(duration);
    return i < 0 ? null : (best.data.bestW[i] ?? null);
  };
  const hasBest = curveDurations.some(d => finite(bestAt(d)));
  const hasCurve = curve.some(finite);
  const curveMax =
      Math.ceil(
        Math.max(
          200,
          ...curve.filter(finite),
          ...curveDurations.map(bestAt).filter(finite),
        ) / 200,
      ) * 200,
    curveW = Math.max(1, curveWidth),
    curveH = 216,
    cx = (d: number) => 48 + (Math.log(d / 5) / Math.log(7200 / 5)) * (curveW - 84),
    cy = (v: number) => 180 - (v / curveMax) * 142;
  const curvePath = (values: (number | null)[]) => {
    let connected = false;
    return values
      .map((v, i) => {
        if (v === null) {
          connected = false;
          return '';
        }
        const path = `${connected ? 'L' : 'M'}${cx(curveDurations[i])},${cy(v)}`;
        connected = true;
        return path;
      })
      .join(' ');
  };
  const curveLabel = (d: number) =>
    d >= 3600 ? formatHoursMinutes(d) : formatDurationCompact(d);
  const readout = formatReadout(activeFigure);
  readout.speed = formatSpeedKmh(activeFigure?.speed, 'metric').toUpperCase();
  readout.elevation = formatMeters(activeFigure?.elevation).toUpperCase();
  readout.cadence = readout.cadence.toUpperCase();
  readout.heartRate = readout.heartRate.toUpperCase();
  for (const key of Object.keys(readout)) if (readout[key] === ABSENT_VALUE) readout[key] = '';
  const thresholdLabel = threshold === null ? '' : `Threshold ${f.watts(threshold)}`;
  return (
    <div className="ride-analysis-page" ref={ref}>
      <Link className="ride-analysis-back" to={`/activities/${ride.id}`}>
        <span>‹</span>
        <b>{title}</b>
        <span>
          {date} · {rider}
        </span>
      </Link>
      <header className="ride-analysis-head">
        <h1>Ride analysis</h1>
      </header>
      <div className="ride-analysis-scope">
        <Words
          label="Ride analysis scope"
          values={[
            { id: 'whole', name: 'Whole ride' },
            ...spans.map((s) => ({ id: s.id, name: s.name })),
          ]}
          current={scope?.id ?? 'whole'}
          onChange={changeScope}
        />
        {range && (
          <button
            className="ride-text-button"
            onClick={() => {
              setRange(null);
              setRangeAnchor(null);
            }}
          >
            Clear range
          </button>
        )}
      </div>
      <dl
        className="ride-page-stats ride-analysis-stats"
        data-range-start={range?.[0] ?? ''}
        data-range-end={range?.[1] ?? ''}
      >
        {[
          ['Distance', summaryText.distance],
          ['Elevation', summaryText.elevation],
          ['Time', summaryText.time],
          ['Avg power', mono(summary.power, 'W')],
        ].filter(([, value]) => value !== '' && value !== ABSENT_VALUE).map(([name, value]) => (
          <div key={name}>
            <dt>{name}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <div className="ride-figure-line">
        <span>
          <i />
          Climbs on this ride
        </span>
        <Words
          label="Ride analysis axis"
          values={[
            { id: 'distance', name: 'Distance' },
            { id: 'time', name: 'Time' },
          ]}
          current={axis}
          onChange={setAxis}
        />
      </div>
      <div className="ride-instruments" data-scrub-index={scrub}>
        <div className="ride-scrub-distance">
          <output
            style={{
              left: active
                ? Math.max(left, Math.min(width - right - 40, x(active)))
                : left,
            }}
          >
            {active
              ? `${labelX(axisValue(active))}${unit ? ` ${unit}` : ''}`
              : ABSENT_VALUE}
          </output>
        </div>
        {rows.map((row) => {
          const field = row.key as 'elevation',
            values = figureSamples.map((p) => p[field]).filter(finite),
            floor =
              row.key === 'elevation' && values.length
                ? Math.floor(Math.min(...values) / 10) * 10
                : 0,
            max = Math.max(
              floor + row.step,
              ...values,
              row.key === 'power' ? (threshold ?? 0) : 0,
            ),
            ceiling =
              floor + (max - floor) * (row.key === 'elevation' ? 1.12 : 1.08),
            bottom = row.height,
            y = (v: number) =>
              bottom - ((v - floor) / (ceiling - floor)) * bottom,
            value = activeFigure?.[field] ?? null;
          return (
            <svg
              className="ride-instrument"
              key={row.key}
              data-metric={row.key}
              viewBox={`0 0 ${width} ${row.height}`}
              role={row.key === 'power' && (estimated || training?.threshold?.estimate) ? 'group' : 'img'}
              aria-label={row.name}
              onPointerDown={pointerDown}
              onPointerMove={pointerMove}
              onPointerUp={pointerUp}
              onPointerCancel={() => {
                setDragging(false);
                drag.current = null;
              }}
            >
              <rect
                className="ride-instrument-frame"
                x={left}
                y={0.5}
                width={plotW}
                height={row.height - 1}
              />
              {Array.from(
                { length: Math.ceil(ceiling / row.step) + 1 },
                (_, i) => i * row.step,
              )
                .filter((v, i) => y(v) > 10 && y(v) < row.height - 10 && i % Math.max(1, Math.ceil(24 / (row.height * row.step / (ceiling - floor)))) === 0)
                .map((v) => (
                  <g key={v}>
                    <line
                      className="ride-instrument-grid"
                      x1={left}
                      x2={width - right}
                      y1={y(v)}
                      y2={y(v)}
                    />
                    <line
                      className="ride-instrument-tick"
                      x1={left - 5}
                      x2={left}
                      y1={y(v)}
                      y2={y(v)}
                    />
                    <text x={left - 9} y={y(v) + 3} textAnchor="end">
                      {formatInteger(v)}
                    </text>
                  </g>
                ))}
              {ticks
                .filter((t) => t.major && t.value > 0)
                .map((t) => (
                  <line
                    className="ride-instrument-grid"
                    key={t.value}
                    x1={left + (t.value / extent) * plotW}
                    x2={left + (t.value / extent) * plotW}
                    y1={0}
                    y2={row.height}
                  />
                ))}
              {range && scopeSamples[range[0]] && (
                <rect
                  className="ride-range-fill"
                  x={x(scopeSamples[range[0]])}
                  y={0}
                  width={Math.max(
                    1,
                    x(scopeSamples[range[1]]) - x(scopeSamples[range[0]]),
                  )}
                  height={row.height}
                />
              )}
              {row.key === 'elevation' && figureSamples.length > 1 && (
                <path
                  className="ride-instrument-fill"
                  d={`${pathFor(figureSamples, (p) => p[field], x, y)} L${formatFixed(x(figureSamples.at(-1)!), 2)},${formatFixed(bottom, 2)} L${formatFixed(x(figureSamples[0]), 2)},${formatFixed(bottom, 2)} Z`}
                />
              )}
              <path
                className={`ride-instrument-trace ${row.key === 'power' ? 'ride-instrument-trace--power' : ''}`}
                data-reduction-method={figure.descriptor.method}
                data-bin-distance-m={figure.descriptor.binDistanceM ?? ''}
                data-window-samples={figure.descriptor.smoothingWindowSamples ?? ''}
                data-preserves-extrema={String(figure.descriptor.preservesExtrema)}
                d={pathFor(figureSamples, (p) => p[field], x, y)}
              />
              {!scope &&
                spans.map((s) => (
                  <path
                    key={s.id}
                    className="ride-counted-trace"
                    data-climb-id={s.id}
                    d={pathFor(
                      figureSamples.filter(
                        (p) => p.t >= s.start && p.t <= s.end,
                      ),
                      (p) => p[field],
                      x,
                      y,
                    )}
                  />
                ))}
              {row.key === 'power' && threshold !== null && (
                <line
                  className="ride-threshold-line"
                  x1={left}
                  x2={width - right}
                  y1={y(threshold)}
                  y2={y(threshold)}
                />
              )}
              <rect
                className="ride-instrument-label-ground"
                x={left + 1}
                y={1}
                width={(row.name.length + row.unit.length + 3) * 6.5}
                height={17}
              />
              <text className="ride-instrument-label" x={left + 8} y={12}>
                {row.name.toUpperCase()} · {row.unit}
              </text>
              {row.key === 'power' && (
                <g>
                  <rect
                    className="ride-instrument-label-ground"
                    x={width - right - 132}
                    y={
                      threshold === null
                        ? row.height - 30
                        : Math.max(22, y(threshold) - 17)
                    }
                    width={130}
                    height={15}
                  />
                  {training?.threshold?.estimate ? (
                    <foreignObject
                      x={width - right - 158}
                      y={Math.max(28, y(threshold!) - 20)}
                      width={156}
                      height={28}
                      onPointerDown={event => event.stopPropagation()}
                      onPointerMove={event => event.stopPropagation()}
                      onPointerUp={event => event.stopPropagation()}
                    >
                      <div className="ride-estimate-readout">
                        Threshold <EstimatedValue measurement={training.threshold} formatValue={f.watts} />
                      </div>
                    </foreignObject>
                  ) : <text
                    className="ride-threshold-label"
                    x={width - right - 6}
                    y={
                      threshold === null
                        ? row.height - 18
                        : Math.max(34, y(threshold) - 5)
                    }
                    textAnchor="end"
                  >
                    {thresholdLabel.toUpperCase()}
                  </text>}
                </g>
              )}
              {active && (
                <g>
                  <line
                    className="ride-scrub-line"
                    x1={x(active)}
                    x2={x(active)}
                    y1={0}
                    y2={row.height}
                  />
                  {value !== null && (
                    <circle
                      className="ride-scrub-dot"
                      cx={x(active)}
                      cy={y(value)}
                      r={2.8}
                    />
                  )}
                </g>
              )}
              <rect
                className="ride-readout-box"
                x={width - right - 80}
                y={5}
                width={74}
                height={20}
              />
              {row.key === 'power' && estimated ? (
                <foreignObject
                  className="ride-instrument-readout"
                  x={width - right - 80}
                  y={5}
                  width={74}
                  height={28}
                  onPointerDown={event => event.stopPropagation()}
                  onPointerMove={event => event.stopPropagation()}
                  onPointerUp={event => event.stopPropagation()}
                >
                  <div className="ride-estimate-readout">
                    <EstimatedValue measurement={{value: activeFigure?.power, estimate: true}} formatValue={f.watts} />
                  </div>
                </foreignObject>
              ) : <text
                className="ride-instrument-readout"
                x={width - right - 12}
                y={19}
                textAnchor="end"
              >
                {readout[row.key]}
              </text>}
            </svg>
          );
        })}
        <svg
          className="ride-instrument-axis"
          viewBox={`0 0 ${width} 46`}
          aria-label={axis === 'time' ? 'Duration' : 'Distance'}
        >
          {ticks.map((t) => (
            <g key={t.value}>
              <line
                data-minor-tick={t.major ? undefined : true}
                x1={left + (t.value / extent) * plotW}
                x2={left + (t.value / extent) * plotW}
                y1={0}
                y2={t.major ? 6 : 3}
              />
              {t.major && (
                <text
                  x={left + (t.value / extent) * plotW}
                  y={18}
                  textAnchor={left + (t.value / extent) * plotW > width - right - 36 ? 'end' : 'middle'}
                >
                  {axis === 'time'
                    ? t.value === 0 ? '0:00' : f.duration(t.value)
                    : formatInteger(t.value / (unit === 'M' ? 1 : 1000))}
                </text>
              )}
            </g>
          ))}
          <text x={left + plotW / 2} y={40} textAnchor="middle">
            {axis === 'time' ? 'DURATION' : `DISTANCE · ${unit}`}
          </text>
        </svg>
        <div className="ride-analysis-keyboard">
          <input
            type="range"
            aria-label="Ride analysis scrub"
            min={0}
            max={Math.max(0, scopeSamples.length - 1)}
            value={scrub}
            onChange={(e) => setScrub(Number(e.target.value))}
          />
          <button
            className="ride-text-button"
            aria-pressed={rangeAnchor !== null}
            onClick={selectKeyboardRange}
          >
            Analyze selected
          </button>
        </div>
        <table className="ride-instrument-table">
          <caption>
            {active ? `${labelX(axisValue(active))} ${unit}` : ABSENT_VALUE}
          </caption>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <th>{row.name}</th>
                <td>{row.key === 'power' && estimated && finite(activeFigure?.power)
                  ? <span aria-label={`Estimated ${f.watts(activeFigure?.power).replace(/ W$/, ' watts')}`}>{readout[row.key]}</span>
                  : readout[row.key]}</td>
              </tr>
            ))}
            <tr>
              <th>Grade</th>
              <td>{readout.grade}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div className="ride-analysis-columns">
        <div className="ride-analysis-column">
          <section>
            <header className="ride-page-heading">
              <h2>Power curve</h2>
              <span className="ride-words">
                <b>This ride</b>
                {hasBest ? <span>Your best</span> : null}
              </span>
            </header>
            <div className="ride-analysis-figure" ref={curveRef}>
              <svg
                viewBox={`0 0 ${curveW} ${curveH}`}
                role="img"
                aria-label="Power curve"
              >
                <rect
                  className="ride-instrument-frame"
                  x={48}
                  y={24}
                  width={curveW - 84}
                  height={156}
                />
                {[0, 0.25, 0.5, 0.75, 1].map((t) => (
                  <g key={t}>
                    <line
                      className="ride-instrument-grid"
                      x1={48}
                      x2={curveW - 36}
                      y1={cy(t * curveMax)}
                      y2={cy(t * curveMax)}
                    />
                    <text x={40} y={cy(t * curveMax) + 4} textAnchor="end">
                      {mono(t * curveMax)}
                    </text>
                  </g>
                ))}
                {(curveW < 380 ? [5, 300, 7200] : [5, 60, 300, 1200, 7200]).map((d) => (
                  <g key={d}>
                    <line
                      className="ride-instrument-grid"
                      x1={cx(d)}
                      x2={cx(d)}
                      y1={24}
                      y2={180}
                    />
                    <text x={cx(d)} y={195} textAnchor="middle">
                      {curveLabel(d)}
                    </text>
                  </g>
                ))}
                <text x={54} y={16}>
                  POWER · W
                </text>
                <path
                  className="ride-instrument-trace ride-instrument-trace--power"
                  d={curvePath(curve)}
                />
                <path
                  className="ride-curve-best"
                  d={curvePath(curveDurations.map(bestAt))}
                />
                <text x={curveW / 2} y={210} textAnchor="middle">
                  DURATION
                </text>
              </svg>
              <table className="ride-analysis-table">
                <thead>
                  <tr>
                    <th>Duration</th>
                    {hasCurve ? <th>This ride</th> : null}
                    {hasBest ? <th>Your best</th> : null}
                    {hasCurve && hasBest ? <th>Δ W</th> : null}
                  </tr>
                </thead>
                <tbody>
                  {curveDurations.map((d, i) => {
                    if (![5, 30, 60, 300, 1200, 3600, 7200].includes(d))
                      return null;
                    const v = curve[i],
                      b = bestAt(d);
                    if (v === null && b === null) return null;
                    return (
                      <tr key={d}>
                        <td>{curveLabel(d)}</td>
                        {hasCurve ? <td>{mono(v)}</td> : null}
                        {hasBest ? <td>{mono(b)}</td> : null}
                        {hasCurve && hasBest ? <td>{mono(v === null || b === null ? null : v - b)}</td> : null}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
          <Link
            className="ride-page-kv ride-analysis-log"
            to={`/activities/${ride.id}/log`}
          >
            <span>Ride log</span>
            <span>›</span>
          </Link>
        </div>
        <div className="ride-analysis-column">
          <section>
            <header className="ride-page-heading">
              <h2>Power zones</h2>
              <span className="ride-analysis-threshold">{threshold === null ? '' : <>
                Threshold <EstimatedValue measurement={{...training?.threshold, value: threshold}} formatValue={f.watts} />
              </>}</span>
            </header>
            <div className="ride-analysis-figure">
              <table className="ride-analysis-table ride-zones">
                <thead>
                  <tr>
                    <th>Zone</th>
                    <th>Range</th>
                    <th />
                    <th>Time</th>
                    {zoneDenominator ? <th>Share <span>{f.duration(zoneDenominator.durationS)}</span></th> : null}
                  </tr>
                </thead>
                <tbody>
                  {[0, 1, 2, 3, 4, 5, 6].map((i) => {
                    const time = zones?.times[i],
                      share = zones && zoneDenominator?.durationS
                        ? (zones.shares?.[i] ?? 0) / 100
                        : null;
                    return (
                      <tr key={i}>
                        <td>Z{formatInteger(i + 1)}</td>
                        <td>
                          {!zones?.ranges[i] ? '' : zones.ranges[i][1] === null
                            ? `${formatWatts(zones.ranges[i][0])}+`
                            : `${formatInteger(zones.ranges[i][0])}–${formatWatts(zones.ranges[i][1])}`}
                        </td>
                        <td className="ride-zone-bar">
                          <span
                            style={{
                              width: `${zones?.total ? (zones.times[i] / Math.max(...zones.times)) * 100 : 0}%`,
                              background: [
                                'var(--climb-band-0)',
                                'var(--br-card)',
                                'var(--br-ink-faint)',
                                'var(--br-ink-muted)',
                                'var(--br-ink-soft)',
                                'color-mix(in srgb,var(--br-ink) 60%,var(--br-ink-soft))',
                                'var(--br-ink)',
                              ][i],
                            }}
                          />
                        </td>
                        <td>
                          {time === undefined || !zones?.total
                            ? ''
                            : time === 0 ? '0:00' : f.duration(time)}
                        </td>
                        {zoneDenominator ? <td>{share === null ? '' : formatPercent(share * 100, 0)}</td> : null}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
          <section>
            <h2>Ride metrics</h2>
            <dl className="ride-metrics">
              {[
                ['Avg power', mono(summary.power, 'W')],
                ['Max power', mono(maximum, 'W')],
                [
                  'Avg speed',
                  (training?.avgSpeedMps ?? null) === null
                    ? ABSENT_VALUE
                    : f.speedKmh(training!.avgSpeedMps! * 3.6),
                ],
                [
                  'Max speed',
                  (training?.maxSpeedMps ?? null) === null
                    ? ABSENT_VALUE
                    : f.speedKmh(training!.maxSpeedMps! * 3.6),
                ],
                ['Cadence', mono(training?.avgCadenceRpm ?? null, 'rpm')],
                ['Max cadence', mono(training?.maxCadenceRpm ?? null, 'rpm')],
                ['Moving', moving === null ? ABSENT_VALUE : f.duration(moving)],
                [
                  'Elapsed',
                  summary.time === null
                    ? ABSENT_VALUE
                    : f.duration(summary.time),
                ],
              ].filter(([, value]) => value !== '' && value !== ABSENT_VALUE).map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          </section>
        </div>
      </div>
    </div>
  );
}
