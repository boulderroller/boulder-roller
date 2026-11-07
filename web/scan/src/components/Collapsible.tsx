import { ReactNode, useState } from 'react';

type CollapsibleProps = {
  label: string;
  defaultOpen?: boolean;
  children: ReactNode;
};

/**
 * A styled expand/collapse section for progressive disclosure.
 * Used to hide technical details behind a toggle.
 */
export default function Collapsible({ label, defaultOpen = false, children }: CollapsibleProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div className="collapsible">
      <button
        type="button"
        className="collapsible__trigger"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
      >
        <span className={`collapsible__chevron${isOpen ? ' collapsible__chevron--open' : ''}`}>
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <path d="M4.5 2.5L8 6L4.5 9.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
        <span className="collapsible__label">{label}</span>
      </button>
      {isOpen ? (
        <div className="collapsible__content">
          {children}
        </div>
      ) : null}
    </div>
  );
}
