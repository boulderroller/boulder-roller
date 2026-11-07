import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';

// The hold capsule (constitution: the only filled buttons in the app).
// Money commits by holding, not clicking: press and keep pressing for the
// hold time and the capsule fills, then commits once. Release early and
// nothing happens. Blue for money in, gray for money out.

const HOLD_MS = 600;

interface HoldCapsuleProps {
  label: string;
  tone: 'in' | 'out';
  disabled?: boolean;
  busy?: boolean;
  onCommit: () => void;
}

export default function HoldCapsule({ label, tone, disabled = false, busy = false, onCommit }: HoldCapsuleProps) {
  const [progress, setProgress] = useState(0);
  const startedAt = useRef<number | null>(null);
  const frame = useRef<number | null>(null);
  const committed = useRef(false);

  const stop = useCallback(() => {
    if (frame.current != null) window.cancelAnimationFrame(frame.current);
    frame.current = null;
    startedAt.current = null;
    setProgress(0);
  }, []);

  const tick = useCallback(() => {
    if (startedAt.current == null) return;
    const elapsed = performance.now() - startedAt.current;
    const next = Math.min(1, elapsed / HOLD_MS);
    setProgress(next);
    if (next >= 1) {
      if (!committed.current) {
        committed.current = true;
        onCommit();
      }
      stop();
      return;
    }
    frame.current = window.requestAnimationFrame(tick);
  }, [onCommit, stop]);

  const start = useCallback(() => {
    if (disabled || busy || startedAt.current != null) return;
    committed.current = false;
    startedAt.current = performance.now();
    frame.current = window.requestAnimationFrame(tick);
  }, [busy, disabled, tick]);

  useEffect(() => stop, [stop]);
  useEffect(() => {
    if (busy || disabled) stop();
    else committed.current = false;
  }, [busy, disabled, stop]);

  const onPointerDown = (event: PointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    start();
  };
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.repeat) return;
    if (event.key === ' ' || event.key === 'Enter') {
      event.preventDefault();
      start();
    }
  };
  const onKeyUp = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === ' ' || event.key === 'Enter') {
      event.preventDefault();
      stop();
    }
  };

  return (
    <button
      type="button"
      className="portfolio-capsule"
      data-tone={tone}
      data-holding={progress > 0 ? 'true' : 'false'}
      disabled={disabled || busy}
      aria-busy={busy}
      onPointerDown={onPointerDown}
      onPointerUp={stop}
      onPointerCancel={stop}
      onPointerLeave={stop}
      onKeyDown={onKeyDown}
      onKeyUp={onKeyUp}
      onClick={(event) => {
        // Native HoldCapsule parity: a timed hold is not a VoiceOver gate.
        // Pointer clicks have detail > 0; held keyboard defaults are cancelled.
        if (event.detail === 0 && !disabled && !busy && !committed.current) {
          committed.current = true;
          onCommit();
        }
      }}
      onBlur={stop}
      onContextMenu={(event) => event.preventDefault()}
      style={{ ['--hold-progress' as string]: progress }}
    >
      <span className="portfolio-capsule__fill" aria-hidden="true" />
      <span className="portfolio-capsule__label">{label}</span>
    </button>
  );
}
