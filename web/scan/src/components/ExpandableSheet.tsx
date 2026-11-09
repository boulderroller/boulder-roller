import { useRef, useState, type PointerEvent, type KeyboardEvent } from "react";
/** Shared Observatory gesture grammar: looking, reading, maximum; tap, drag, arrows. */
export function useExpandableSheet(
  initial: "collapsed" | "reading" | "max" = "collapsed",
) {
  const [sheet, setSheet] = useState(initial);
  const drag = useRef<{ y: number; moved: boolean } | null>(null);
  const expanded = sheet !== "collapsed";
  const up = () => setSheet(expanded ? "max" : "reading");
  const down = () => setSheet(sheet === "max" ? "reading" : "collapsed");
  return {
    sheet,
    expanded,
    setSheet,
    grip: {
      onPointerDown: (e: PointerEvent<HTMLElement>) => {
        drag.current = { y: e.clientY, moved: false };
        e.currentTarget.setPointerCapture(e.pointerId);
      },
      onPointerUp: (e: PointerEvent<HTMLElement>) => {
        if (!drag.current) return;
        const delta = e.clientY - drag.current.y;
        drag.current.moved = Math.abs(delta) > 35;
        if (drag.current.moved) {
          if (delta < 0) up();
          else down();
        }
      },
      onPointerCancel: () => {
        drag.current = null;
      },
      onClick: () => {
        if (drag.current?.moved) {
          drag.current = null;
          return;
        }
        setSheet(expanded ? "collapsed" : "reading");
      },
      onKeyDown: (e: KeyboardEvent<HTMLElement>) => {
        if (e.key === "ArrowUp") {
          e.preventDefault();
          up();
        }
        if (e.key === "ArrowDown") {
          e.preventDefault();
          down();
        }
        if (e.key === "Home") {
          e.preventDefault();
          setSheet("collapsed");
        }
        if (e.key === "End") {
          e.preventDefault();
          setSheet("max");
        }
      },
    },
  };
}
