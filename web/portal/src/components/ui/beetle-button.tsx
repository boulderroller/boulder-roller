import { ButtonHTMLAttributes, forwardRef } from 'react';

/**
 * BeetleButton - Brutalist button with proper interaction states
 * 
 * Key principles from the knowledge dump:
 * 1. Every interaction gets fast acknowledgment (<100ms)
 * 2. Shadow literally depresses on click (physical feedback)
 * 3. Hover lifts, active presses, disabled stays put
 * 4. Transitions are tight: 100-150ms
 */

interface BeetleButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  isLoading?: boolean;
  loadingLabel?: string;
}

export const BeetleButton = forwardRef<HTMLButtonElement, BeetleButtonProps>(
  ({ 
    variant = 'primary', 
    size = 'md', 
    isLoading = false,
    loadingLabel = 'Loading',
    className = '',
    children,
    disabled,
    ...props 
  }, ref) => {
    const buttonClassName = ['beetle-button', `beetle-button--${size}`, className].filter(Boolean).join(' ');

    return (
      <button
        ref={ref}
        disabled={disabled || isLoading}
        aria-busy={isLoading || undefined}
        className={buttonClassName}
        data-variant={variant}
        {...props}
      >
        {isLoading ? (
          <span className="beetle-button__loading">
            <span>{loadingLabel}</span>
          </span>
        ) : (
          children
        )}
      </button>
    );
  }
);

BeetleButton.displayName = 'BeetleButton';
