import { ReactNode } from 'react';

type TooltipProps = {
  text: string;
  children: ReactNode;
};

/**
 * Lightweight tooltip using the native title attribute.
 * Wraps children in a span with hover text.
 */
export default function Tooltip({ text, children }: TooltipProps) {
  return (
    <span className="tooltip-trigger" title={text}>
      {children}
    </span>
  );
}
