import type { CSSProperties, HTMLAttributes } from 'react';
import { cn } from '../ui/utils';

type SlotProps = HTMLAttributes<HTMLSpanElement> & {
  variant?: 'text' | 'number' | 'avatar' | 'glyph';
  width?: CSSProperties['width'];
};

/** The value's space, before arrival. Never a value, status or illustration. */
export function Slot({ variant = 'text', width, className, style, ...props }: SlotProps) {
  return <span {...props} aria-hidden="true" data-slot={variant} className={cn('ledger-slot', `ledger-slot--${variant}`, className)} style={{ width, ...style, height: variant === 'text' ? 8 : variant === 'avatar' ? 40 : 2 }} />;
}

export function SlotRows({ count = 6, className = '' }: { count?: number; className?: string }) {
  return <div className={className}>{Array.from({ length: count }, (_, i) => <div className="ledger-slot-row" key={i}>
    <Slot variant="glyph" /><span className="ledger-slot-copy"><Slot width="12ch" /><Slot width="18ch" /></span><Slot variant="number" width="6ch" />
  </div>)}</div>;
}
