import { useEffect, useId, useRef, useState } from 'react';
import * as Popover from '@radix-ui/react-popover';
import { estimateCopyLines } from '../lib/estimateCopy';
import '../styles/estimated-value.css';

type EstimateMeasurement = {
  value: number | null | undefined;
  estimate?: boolean;
  basis?: string | null;
  range?: readonly [number, number] | null;
};

type EstimatedValueProps = {
  measurement: EstimateMeasurement;
  /** The surface's existing shared formatter, also used for both range ends. */
  formatValue: (value: number) => string;
  /** Which edge of the value the card lines up with; right-aligned values use "end". */
  align?: 'start' | 'end';
  openOnFocus?: boolean;
};

function spokenValue(formatted: string): string {
  return formatted.replace(/\bW$/, 'watts').replace(/\bkcal$/i, 'kilocalories').replace(/\bbpm$/i, 'beats per minute');
}

function formatRange(range: readonly [number, number], format: (value: number) => string): string {
  const low = format(range[0]), high = format(range[1]);
  const unit = high.match(/\s+[^\d\s]+$/)?.[0];
  return `${unit && low.endsWith(unit) ? low.slice(0, -unit.length) : low}–${high}`;
}

/** Display only: estimate provenance and bounds are supplied by the caller. */
export function EstimatedValue({ measurement, formatValue, align = 'start', openOnFocus = false }: EstimatedValueProps) {
  const { value, estimate, basis, range } = measurement;
  const descriptionId = useId();
  const [open, setOpen] = useState(false);
  const pinned = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const trigger = useRef<HTMLButtonElement>(null);
  const card = useRef<HTMLDivElement>(null);
  const clearTimer = () => clearTimeout(timer.current);
  useEffect(() => () => clearTimeout(timer.current), []);

  if (value == null || !Number.isFinite(value)) return null;
  const formatted = formatValue(value);
  if (!estimate) return <>{formatted}</>;
  const name = `Estimated ${spokenValue(formatted)}`;
  const copy = estimateCopyLines(basis);
  const formattedRange = range?.length === 2 && range.every(Number.isFinite) ? formatRange(range, formatValue) : null;
  if (formattedRange === null && copy.length === 0) {
    return <span className="estimated-value">
      <span className="sr-only">{name}</span>
      <span aria-hidden="true"><span className="estimated-value__mark">≈</span>{formatted}</span>
    </span>;
  }
  const close = () => {
    clearTimer();
    setOpen(false);
  };
  const leave = () => {
    if (!pinned.current) timer.current = setTimeout(close, 150);
  };
  const blur = (target: EventTarget | null) => {
    if (!(target instanceof Node) || (!trigger.current?.contains(target) && !card.current?.contains(target))) close();
  };

  return (
    <Popover.Root open={open} onOpenChange={next => { clearTimer(); setOpen(next); }} modal={false}>
      <Popover.Trigger asChild>
        <button
          ref={trigger}
          type="button"
          className="estimated-value"
          aria-label={name}
          aria-describedby={open ? descriptionId : undefined}
          onFocus={() => {
            if (openOnFocus && !open) { clearTimer(); pinned.current = false; setOpen(true); }
          }}
          onPointerEnter={event => {
            clearTimer();
            if (event.pointerType === 'mouse' && !open) {
              pinned.current = false;
              setOpen(true);
            }
          }}
          onPointerLeave={leave}
          onBlur={event => blur(event.relatedTarget)}
          onClick={event => {
            // A hover-open card stays open on its first deliberate activation.
            event.preventDefault();
            clearTimer();
            const next = !open || !pinned.current;
            pinned.current = next;
            setOpen(next);
          }}
        ><span className="estimated-value__mark" aria-hidden="true">≈</span>{formatted}</button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          ref={card}
          className="estimated-value__card"
          aria-label={name}
          align={align}
          sideOffset={6}
          collisionPadding={12}
          onOpenAutoFocus={event => event.preventDefault()}
          onCloseAutoFocus={event => event.preventDefault()}
          onEscapeKeyDown={() => {
            if (pinned.current || card.current?.contains(document.activeElement)) trigger.current?.focus();
          }}
          onPointerEnter={clearTimer}
          onPointerLeave={leave}
          onBlur={event => blur(event.relatedTarget)}
        >
          <div id={descriptionId} className="estimated-value__description">
            <div className="estimated-value__numbers">
              <span className="estimated-value__number"><span className="estimated-value__mark" aria-hidden="true">≈</span>{formatted}</span>
              {formattedRange !== null ? <span className="estimated-value__range">{formattedRange}</span> : null}
            </div>
            {copy.map((line, index) => <p className="estimated-value__copy" key={index}>{line}</p>)}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
