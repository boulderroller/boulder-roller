import { useRef, useState, type ReactNode } from 'react';

/** Resizing changes the viewport, never the ride selection. */
export function V7MapFrame({ adjustable, children }: { adjustable: boolean; children: ReactNode }) {
  const [height, setHeight] = useState(() => window.matchMedia('(max-width: 600px)').matches ? 210 : 258);
  const gesture = useRef<{ id: number; y: number; height: number } | null>(null);
  const clamp = (value: number) => Math.round(Math.max(180, Math.min(620, value)));
  return <div className={`v7-map-frame ${adjustable ? 'is-adjustable' : ''}`} style={adjustable ? { height } : undefined}>
    {children}
    {adjustable && <div className="v7-map-resizer" role="separator" tabIndex={0} aria-label="Map height" aria-orientation="horizontal" aria-valuemin={180} aria-valuemax={620} aria-valuenow={height} aria-valuetext={`${height} pixels. Drag or use up and down arrows to resize the map.`}
      onPointerDown={e => { if (e.button !== 0 || !e.isPrimary) return; gesture.current = { id: e.pointerId, y: e.clientY, height }; e.currentTarget.setPointerCapture(e.pointerId); }}
      onPointerMove={e => { const g = gesture.current; if (g?.id === e.pointerId) setHeight(clamp(g.height + e.clientY - g.y)); }}
      onPointerUp={e => { if (gesture.current?.id === e.pointerId) gesture.current = null; }}
      onPointerCancel={() => { if (gesture.current) setHeight(gesture.current.height); gesture.current = null; }}
      onKeyDown={e => {
        if (!['ArrowUp','ArrowDown','Home','End','Escape'].includes(e.key)) return;
        if (e.key === 'Escape') { if (gesture.current) { e.preventDefault(); setHeight(gesture.current.height); gesture.current = null; } return; }
        e.preventDefault();
        setHeight(current => clamp(e.key === 'Home' ? 180 : e.key === 'End' ? 620 : current + (e.key === 'ArrowDown' ? 20 : -20)));
      }}><span aria-hidden="true"/></div>}
  </div>;
}
