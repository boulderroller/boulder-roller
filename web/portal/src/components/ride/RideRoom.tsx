import {
  lazy,
  Suspense,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent,
  type ReactNode,
} from 'react';
import { Link } from 'react-router-dom';
import { flushSync } from 'react-dom';
import { useFormatters } from '../../hooks/useFormatters';
import { ABSENT_VALUE, formatInteger, roundToDigits } from '../../lib/formatters';
import type { RoutePreview } from '../../lib/api';
import ClimbShapeGlyph from '../climbs/ClimbShapeGlyph';
import { ClimbPower } from '../climb/ClimbPower';
import { MAP_GROUND } from '../climb/mapGroundPalette';
import {
  nearest,
  pathFor,
  type RideSample,
  type RideSpan,
  type TimedValue,
} from './rideRoomModel';
import '../../styles/portal-ride-room.css';
const RideRoomMap = lazy(() => import('./RideRoomMap'));
export type RoomViewer = 'owner' | 'stranger';

export function RideRoomTribute({ hasItemization }: { hasItemization: boolean }) {
  return <div className="ride-room-kv">
    <span>CAL tribute</span>
    {!hasItemization && <b>{ABSENT_VALUE}</b>}
  </div>;
}

export function RideRoomIdentity({
  viewer = 'owner',
  riderProfileHref,
  riderDisplayName,
  riderAvatarUrl,
  riderInitials,
  rideStartedLabel,
  placeLabel,
  roomTitle,
  profile,
  spans,
  stats,
  roomSummary,
  actions,
  social,
}: {
  viewer?: RoomViewer;
  riderProfileHref: string | null;
  riderDisplayName: string;
  riderAvatarUrl?: string | null;
  riderInitials: string;
  rideStartedLabel: string;
  placeLabel?: string | null;
  roomTitle: string;
  profile?: Array<{ distanceM: number; elevationM: number }> | null;
  spans?: Array<{ startDistanceM: number; endDistanceM: number }> | null;
  stats: Array<[string, string | null]>;
  roomSummary?: ReactNode;
  actions?: ReactNode;
  social?: ReactNode;
}) {
  return (
    <>
      <div className="ride-room-card-head">
        <IdentityLink
          className="ride-room-avatar"
          to={riderProfileHref}
          aria-label={`Open ${riderDisplayName}'s profile`}
        >
          {riderAvatarUrl ? <img src={riderAvatarUrl} alt="" /> : riderInitials}
        </IdentityLink>
        <div>
          <IdentityLink to={riderProfileHref}>
            <b>{riderDisplayName}</b>
          </IdentityLink>
          <span>
            {rideStartedLabel}
            {placeLabel
              ? `${viewer === 'stranger' && !rideStartedLabel ? '' : ' · '}${placeLabel}`
              : ''}
          </span>
        </div>
        {actions}
      </div>
      <h1 id="ride-detail-title">{roomTitle}</h1>
      {viewer === 'owner' || profile?.length ? (
        <ClimbShapeGlyph
          className="ride-room-spine"
          profile={profile ?? undefined}
          spans={spans ?? undefined}
          width={312}
          height={44}
        />
      ) : null}
      <dl className="ride-room-stats" data-object-layer="ride-stats">
        {stats
          .filter(([, value]) => viewer === 'owner' || value != null)
          .map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
      </dl>
      {roomSummary != null && (
        <p className="ride-room-summary">{roomSummary}</p>
      )}
      {social}
    </>
  );
}

function IdentityLink({
  to,
  children,
  ...props
}: {
  to: string | null;
  children: ReactNode;
  className?: string;
  'aria-label'?: string;
}) {
  return to ? (
    <Link to={to} {...props}>
      {children}
    </Link>
  ) : (
    <span {...props}>{children}</span>
  );
}
export function RideRoomRow({
  href,
  profile,
  name,
  detail,
  value,
  sub,
  viewer = 'owner',
}: {
  href?: string | null;
  profile?: Array<{ distanceM: number; elevationM: number }>;
  name?: string;
  detail?: string | null;
  value?: ReactNode;
  sub?: ReactNode;
  viewer?: RoomViewer;
}) {
  const content = (
    <>
      {viewer === 'owner' || profile?.length ? (
        <ClimbShapeGlyph profile={profile} />
      ) : null}
      <span className="ride-room-row-copy">
        <b>{href ? <Link className="ride-room-row-link" to={href}>{name}</Link> : name}</b>
        {(viewer === 'owner' || detail != null) && <span>{detail}</span>}
      </span>
      {(viewer === 'owner' || value != null || sub != null) && (
        <span className="ride-room-row-value">
          {value}
          {(viewer === 'owner' || sub != null) && <small>{sub}</small>}
        </span>
      )}
    </>
  );
  return <div className="ride-room-row">{content}</div>;
}
export function RideBand({
  samples,
  spans,
  power,
  scrub,
  onScrub,
  width = 1440,
  phone = false,
}: {
  samples: RideSample[];
  spans: RideSpan[];
  power: TimedValue[];
  scrub: number | null;
  onScrub: (i: number | null) => void;
  width?: number;
  phone?: boolean;
}) {
  const f = useFormatters(),
    h = phone ? 104 : 185,
    left = phone ? 34 : 60,
    right = phone ? 14 : 50,
    top = phone ? 18 : 48,
    bottom = h - 25;
  const maxD = samples.at(-1)?.d || 1,
    maxE = Math.max(50, ...samples.map((p) => p.elevation ?? 0)),
    ceiling = Math.ceil(maxE / 50) * 50;
  const x = (p: RideSample) => left + (p.d / maxD) * (width - left - right),
    y = (v: number) => bottom - (v / ceiling) * (bottom - top);
  const line = useMemo(
    () => pathFor(samples, (p) => p.elevation, x, y),
    [samples, width, h, ceiling],
  );
  const fillPath = `${line}L${width - right},${bottom}L${left},${bottom}Z`;
  const p = scrub === null ? null : samples[scrub];
  if (!samples.length) return <div className="ride-band" style={{ height: h }} aria-hidden="true" />;
  return (
    <div className="ride-band" data-scrub-index={scrub ?? ''}>
      <svg
        viewBox={`0 0 ${width} ${h}`}
        role="img"
        aria-label="Ride elevation"
        onPointerMove={(e) => {
          const b = e.currentTarget.getBoundingClientRect();
          // Direct manipulation commits before background map work can take the next frame.
          flushSync(() => onScrub(
            nearest(
              samples,
              Math.max(
                0,
                Math.min(
                  1,
                  (e.clientX - b.left - left) / (b.width - left - right),
                ),
              ) * maxD,
              (p) => p.d,
            ),
          ));
        }}
        onPointerLeave={() => onScrub(null)}
      >
        {Array.from(
          { length: Math.floor(ceiling / 50) + 1 },
          (_, i) => i * 50,
        ).map((v) => (
          <g key={v}>
            <line
              className="ride-band-grid"
              x1={left}
              x2={width - right}
              y1={y(v)}
              y2={y(v)}
            />
            <text x={left - 8} y={y(v) + 3} textAnchor="end">
              {formatInteger(v)}
            </text>
          </g>
        ))}
        {line && (
          <>
            <path className="ride-band-fill" d={fillPath} />
            <path className="ride-band-line" d={line} />
          </>
        )}
        {spans.map((s) => {
          const inside = samples.filter((p) => p.t >= s.start && p.t <= s.end);
          return (
            <g key={s.id}>
              <path
                className="ride-counted-trace"
                d={pathFor(inside, (p) => p.elevation, x, y)}
              />
              {!phone && inside.length > 1 && (
                <foreignObject className="ride-band-name" x={x(inside[0])} y={5} width={240} height={42}>
                  <div>{s.name}</div>
                  <div className="ride-band-effort"><span>{f.duration(s.pattern.durationS ?? null)}</span><ClimbPower power={s.pattern} /></div>
                </foreignObject>
              )}
            </g>
          );
        })}
        {Array.from(
          { length: Math.floor(maxD / 10000) + 1 },
          (_, i) => i * 10000,
        ).map((d) => (
          <text
            key={d}
            x={left + (d / maxD) * (width - left - right)}
            y={h - 7}
            textAnchor="middle"
          >
            {formatInteger(d / 1000)}
            {d === 0 ? ' km' : ''}
          </text>
        ))}
        {p && (
          <g className="ride-scrub">
            <line x1={x(p)} x2={x(p)} y1={top} y2={bottom} />
            <circle cx={x(p)} cy={y(p.elevation ?? 0)} r={3} />
            <text
              x={Math.min(width - right - 65, Math.max(left, x(p) + 8))}
              y={top + 12}
            >
              {f.kilometers(p.d / 1000)}
            </text>
          </g>
        )}
      </svg>
      <input
        className="ride-band-keyboard"
        type="range"
        aria-label="Ride elevation scrub"
        min={0}
        max={Math.max(0, samples.length - 1)}
        value={scrub ?? 0}
        onChange={(e) => onScrub(Number(e.target.value))}
      />
    </div>
  );
}
export function RideRoomGeography({
  samples,
  spans,
  power,
  identity,
  children,
  viewer = 'owner',
  routePreview,
}: {
  samples: RideSample[];
  spans: RideSpan[];
  power: TimedValue[];
  identity: ReactNode;
  children: ReactNode;
  viewer?: RoomViewer;
  routePreview?: RoutePreview | null;
}) {
  const ref = useRef<HTMLDivElement>(null),
    card = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 1440, available: 782, card: 250 }),
    [ground, setGround] = useState(720),
    [sheet, setSheet] = useState<number | null>(null),
    [scrub, setScrub] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{
    x: number;
    y: number;
    initial: number;
    active: boolean;
    phone: boolean;
  } | null>(null);
  useEffect(() => {
    const measure = () => {
      if (!ref.current) return;
      setSize({
        width: ref.current.clientWidth,
        available:
          window.innerHeight -
          (document
            .querySelector('.portal-shell__header')
            ?.getBoundingClientRect().height || 62),
        card: card.current?.offsetHeight ?? 250,
      });
    };
    const observer = new ResizeObserver(measure);
    if (ref.current) observer.observe(ref.current);
    if (card.current) observer.observe(card.current);
    window.addEventListener('resize', measure);
    measure();
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, []);
  const phone = size.width <= 440,
    limit = size.available * 0.72,
    sheetHeight = Math.min(
      limit,
      Math.max(
        150,
        sheet ?? (viewer === 'stranger' ? 150 : size.available * 0.54),
      ),
    );
  const resize = (height: number) =>
    phone
      ? setSheet(Math.min(limit, Math.max(150, height)))
      : setGround(Math.min(1040, Math.max(320, height)));
  const down = (e: PointerEvent<HTMLDivElement>, direct = false) => {
    if (e.button !== 0) return;
    drag.current = {
      x: e.clientX,
      y: e.clientY,
      initial: phone ? sheetHeight : ground,
      active: direct,
      phone,
    };
    if (direct) setDragging(true);
    if (direct) e.currentTarget.setPointerCapture(e.pointerId);
  };
  const move = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d) return;
    const delta = e.clientY - d.y;
    if (!d.active) {
      if (!phone || Math.abs(delta) < Math.abs(e.clientX - d.x) + 6) return;
      d.active = true; setDragging(true);
      e.currentTarget.setPointerCapture(e.pointerId);
    }
    resize(d.initial + delta * (d.phone ? -1 : 1));
  };
  const end = () => {
    drag.current = null; setDragging(false);
  };
  const phoneFitTop = size.card + 32,
    phoneFitHeight = Math.max(
      80,
      size.available - sheetHeight - phoneFitTop - 46,
    );
  const fitBox = phone
    ? {
        top: phoneFitTop,
        left: 30,
        right: 30,
        bottom: Math.max(0, size.available - phoneFitTop - phoneFitHeight),
      }
    : { top: 60, left: 470, right: 70, bottom: 110 };
  return (
    <div
      className="ride-room"
      data-dragging={dragging}
      ref={ref}
      style={
        {
          '--ride-ground-height': `${ground}px`,
          '--ride-available-height': `${size.available}px`,
          '--ride-sheet-height': `${sheetHeight}px`,
          '--ride-map-paper': MAP_GROUND.paper,
          '--ride-map-label': MAP_GROUND.label,
        } as CSSProperties
      }
    >
      <div className="ride-room-ground" data-object-layer="ride-route-map">
        <Suspense fallback={null}>
          <RideRoomMap
            viewer={viewer}
            routePreview={routePreview}
            samples={samples}
            spans={spans}
            scrub={scrub}
            onScrub={setScrub}
            fitBox={fitBox}
            compact={phone && size.available - sheetHeight - phoneFitTop < 200}
          />
        </Suspense>
        <div
          ref={card}
          className="ride-room-card"
          data-object-layer="ride-identity"
        >
          {identity}
        </div>
      </div>
      <div className="ride-room-sheet">
        <div
          className="ride-room-grip"
          role="slider"
          tabIndex={0}
          aria-label="Ride route and elevation"
          aria-valuemin={phone ? 150 : 320}
          aria-valuemax={phone ? roundToDigits(limit, 0) : 1040}
          aria-valuenow={roundToDigits(phone ? sheetHeight : ground, 0)}
          aria-orientation="vertical"
          onPointerDown={(e) => down(e, true)}
          onPointerMove={move}
          onPointerUp={end}
          onPointerCancel={end}
          onKeyDown={(e) => {
            if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(e.key))
              return;
            e.preventDefault();
            resize(
              e.key === 'Home'
                ? phone
                  ? 150
                  : 320
                : e.key === 'End'
                  ? phone
                    ? limit
                    : 1040
                  : (phone ? sheetHeight : ground) +
                    (e.key === 'ArrowUp' ? 40 : -40) * (phone ? 1 : -1),
            );
          }}
        >
          <span />
        </div>
        {(viewer === 'owner' || samples.some((p) => p.elevation !== null)) && (
          <div
            data-object-layer="ride-elevation-climbs"
            onPointerDown={(e) => down(e)}
            onPointerMove={move}
            onPointerUp={end}
            onPointerCancel={end}
          >
            <RideBand
              samples={samples}
              spans={spans}
              power={power}
              scrub={scrub}
              onScrub={setScrub}
              width={size.width}
              phone={phone}
            />
          </div>
        )}
        <div className="ride-room-sheet-scroll">{children}</div>
      </div>
    </div>
  );
}
