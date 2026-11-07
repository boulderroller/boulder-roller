import { InputHTMLAttributes, forwardRef, TextareaHTMLAttributes } from 'react';

/**
 * BeetleInput - Form input with proper focus/hover states
 * 
 * Key principles:
 * 1. Hover advertises interactivity (border color shift)
 * 2. Focus gets clear ring (WCAG 2.1 compliant)
 * 3. Never just remove outline without replacement
 * 4. Transitions are fast (120ms)
 */

interface BeetleInputProps extends InputHTMLAttributes<HTMLInputElement> {
  error?: boolean;
}

export const BeetleInput = forwardRef<HTMLInputElement, BeetleInputProps>(
  ({ error = false, className = '', 'aria-invalid': ariaInvalid, ...props }, ref) => {
    return (
      <input
        ref={ref}
        className={['beetle-input', className].filter(Boolean).join(' ')}
        {...props}
        aria-invalid={ariaInvalid ?? (error ? true : undefined)}
        data-invalid={error ? 'true' : undefined}
      />
    );
  }
);

BeetleInput.displayName = 'BeetleInput';

// Textarea variant
interface BeetleTextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  error?: boolean;
}

export const BeetleTextarea = forwardRef<HTMLTextAreaElement, BeetleTextareaProps>(
  ({ error = false, className = '', 'aria-invalid': ariaInvalid, ...props }, ref) => {
    return (
      <textarea
        ref={ref}
        className={['beetle-input', 'beetle-textarea', className].filter(Boolean).join(' ')}
        {...props}
        aria-invalid={ariaInvalid ?? (error ? true : undefined)}
        data-invalid={error ? 'true' : undefined}
      />
    );
  }
);

BeetleTextarea.displayName = 'BeetleTextarea';
