import { lazy, Suspense, useEffect, useRef, useState, type CSSProperties, type PointerEvent, type ReactNode } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { Maximize2, X } from 'lucide-react';
import type { Climb } from '../../lib/api';
import GeographyCredit from './GeographyCredit';
import ClimbProfileHero from './ClimbProfileHero';
import { MAP_GROUND } from './mapGroundPalette';
import '../../styles/portal-climb-detail.css';

const ClimbMap = lazy(() => import('./ClimbMap'));

export default function ClimbGeography({ climb, identity, children, viewer = 'owner' }: { climb?: Climb; identity?: ReactNode; children?: ReactNode; viewer?: 'owner' | 'stranger' }) {
  const [distance, setDistance] = useState<number | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [dragging, setDragging] = useState(false);
  const returnFocus = useRef<HTMLElement | null>(null);
  const geographyRef = useRef<HTMLElement>(null);
  const identityRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 1440, available: 782, identityHeight: 200 });
  const [groundHeight, setGroundHeight] = useState(720);
  const [sheetHeight, setSheetHeight] = useState<number | null>(null);
  const drag = useRef<{ x: number; y: number; height: number; active: boolean } | null>(null);
  const phone = size.width <= 440;
  const maxSheet = size.available * .72;
  const sheet = Math.min(maxSheet, Math.max(150, sheetHeight ?? size.available * .58));
  const profile = (climb?.elevationProfile ?? []).filter((point) => Number.isFinite(point.distanceM) && Number.isFinite(point.elevationM));
  const first = profile[0]?.distanceM ?? 0;
  const last = profile[profile.length - 1]?.distanceM ?? 0;
  const validProfile = profile.length >= 2 && profile.every((point, i) => i === 0 || point.distanceM > profile[i - 1].distanceM);
  const fraction = distance === null || !validProfile ? null : (distance - first) / (last - first);
  const endpoint = (end: 'start' | 'finish') => { if (validProfile) setDistance(end === 'start' ? first : last); };
  useEffect(() => {
    const geography = geographyRef.current;
    if (!geography) return;
    const measure = () => {
      const header = parseFloat(getComputedStyle(geography).getPropertyValue('--portal-shell-header-height')) || 62;
      setSize({ width: geography.clientWidth, available: window.innerHeight - header, identityHeight: identityRef.current?.offsetHeight ?? 200 });
    };
    const observer = new ResizeObserver(measure);
    observer.observe(geography);
    if (identityRef.current) observer.observe(identityRef.current);
    window.addEventListener('resize', measure);
    measure();
    return () => { observer.disconnect(); window.removeEventListener('resize', measure); };
  }, []);
  const maxSheetValue = Math.round(maxSheet);
  const currentHeightValue = Math.round(phone ? sheet : groundHeight);
  const changeHeight = (value: number) => phone ? setSheetHeight(Math.min(maxSheet, Math.max(150, value))) : setGroundHeight(Math.min(1040, Math.max(320, value)));
  const begin = (event: PointerEvent<HTMLElement>) => {
    if (event.button !== 0 || event.target instanceof Element && event.target.closest('.climb-page-expand')) return;
    drag.current = { x: event.clientX, y: event.clientY, height: phone ? sheet : groundHeight, active: event.target instanceof Element && Boolean(event.target.closest('.climb-page-seam')) };
    if (drag.current.active) { setDragging(true); event.currentTarget.setPointerCapture(event.pointerId); event.preventDefault(); }
  };
  const move = (event: PointerEvent<HTMLElement>) => {
    const start = drag.current;
    if (!start) return;
    const dy = event.clientY - start.y;
    if (!start.active && phone && Math.abs(dy) > Math.abs(event.clientX - start.x) + 6) {
      start.active = true; setDragging(true);
      event.currentTarget.setPointerCapture(event.pointerId);
    }
    if (!start.active) return;
    event.preventDefault();
    changeHeight(start.height + (phone ? -dy : dy));
  };
  const top = phone ? 16 + size.identityHeight + 30 : 70;
  const fitBox = phone
    ? { top, left: 34, right: 34, bottom: sheet + 22 }
    : { top, left: size.width >= 1000 ? 470 : 40, right: 70, bottom: 120 };
  const groundStyle = Object.fromEntries(Object.entries(MAP_GROUND).map(([name, value]) => [`--climb-map-${name}`, value]));
  return <section ref={geographyRef} className="climb-geography climb-page-geography" data-dragging={dragging} data-object-layer="climb-route-elevation" aria-label="Climb route and elevation"
    style={{ ...groundStyle, '--climb-ground-height': `${groundHeight}px`, '--climb-sheet-height': `${sheet}px` } as CSSProperties}>
    <div className="climb-page-ground">
      <Suspense fallback={<div className="climb-map-fallback" aria-busy="true" />}>
        <ClimbMap climb={climb} fraction={fraction} onEndpoint={endpoint} fitBox={fitBox} onExpand={(trigger) => { returnFocus.current = trigger; setExpanded(true); }} />
      </Suspense>
      <div className="climb-page-identity" ref={identityRef}>{identity}</div>
    </div>
    <div className="climb-page-sheet">
      <div className="climb-page-grip" onPointerDownCapture={begin} onPointerMove={move} onPointerUp={() => { drag.current = null; setDragging(false); }} onPointerCancel={() => { drag.current = null; setDragging(false); }}>
        <div className="climb-page-seam">
          <button className="climb-page-expand" type="button" aria-label="Expand map" onClick={event => { returnFocus.current = event.currentTarget; setExpanded(true); }}><Maximize2 size={18} /></button>
          <button type="button" role="slider" aria-label="Climb route and elevation" aria-orientation="vertical"
            aria-valuemin={phone ? 150 : 320} aria-valuemax={phone ? maxSheetValue : 1040} aria-valuenow={currentHeightValue}
            onKeyDown={event => {
              if (event.key === 'Home' || event.key === 'End') { event.preventDefault(); changeHeight(event.key === 'Home' ? phone ? 150 : 320 : phone ? maxSheet : 1040); }
              else if (event.key === 'ArrowUp' || event.key === 'ArrowDown') { event.preventDefault(); changeHeight((phone ? sheet : groundHeight) + (event.key === 'ArrowUp' ? phone ? 40 : -40 : phone ? -40 : 40)); }
            }}><span className="climb-page-handle" /></button>
        </div>
        {(viewer === 'owner' || validProfile) && <div className="climb-detail-route-card__figure climb-detail-route-card__figure--profile">
          {validProfile ? <ClimbProfileHero profile={profile} geographicData={climb?.geographicData} inspectedDistance={distance} onInspect={setDistance} /> : <div className="climb-empty-band" aria-hidden="true" />}
        </div>}
      </div>
      <div className="climb-page-ledger-scroll">{children}
        <div className="climb-ledger-note climb-data-attribution"><GeographyCredit data={climb?.geographicData} /></div>
      </div>
    </div>
    <Dialog.Root open={expanded} onOpenChange={setExpanded}>
      <Dialog.Portal><Dialog.Overlay className="climb-map-overlay" />
        <Dialog.Content className="climb-map-dialog" aria-describedby={undefined} style={groundStyle as CSSProperties} onCloseAutoFocus={(event) => { event.preventDefault(); returnFocus.current?.focus(); }}>
          <Dialog.Title className="climb-sr-only">Climb map</Dialog.Title>
          <Dialog.Close className="climb-map-close" aria-label="Close map"><X size={20} /></Dialog.Close>
          <Suspense fallback={<div className="climb-map-fallback" aria-busy="true" />}><ClimbMap climb={climb} fraction={fraction} onEndpoint={endpoint} expanded /></Suspense>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  </section>;
}
