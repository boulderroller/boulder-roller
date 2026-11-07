import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode, Ref, FormEvent } from 'react';
import { Check, ChevronLeft, ChevronRight, Mail } from 'lucide-react';
import { BeetleButton } from '../ui/beetle-button';
import { BeetleInput } from '../ui/beetle-input';

export function AuthHeader() {
  return (
    <header className="access-entry-page__header">
      <a className="access-entry-page__brand portal-shell__brand" href="https://boulderroller.xyz">
        <span className="portal-shell__brand-mark" aria-hidden="true" />
        Boulder Roller
      </a>
    </header>
  );
}

export function AuthHeading({ title, onBack, headingRef, backDisabled = false }: { title: string; onBack?: () => void; headingRef?: Ref<HTMLHeadingElement>; backDisabled?: boolean }) {
  return (
    <div className="auth-entry-heading">
      {onBack ? (
        <button type="button" className="auth-entry-back" onClick={onBack} disabled={backDisabled}>
          <ChevronLeft aria-hidden="true" /><span>Back</span>
        </button>
      ) : <div className="auth-entry-back-space" aria-hidden="true" />}
      <h1 id="access-entry-title" ref={headingRef} tabIndex={-1}>{title}</h1>
    </div>
  );
}

export function AuthNavigation({ children, icon, helper, className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { icon?: ReactNode; helper?: string }) {
  return (
    <button type="button" className={`auth-entry-row ${className}`} {...props}>
      {icon}
      <span className="auth-entry-row__copy">{children}{helper && <span className="auth-entry-row__helper">{helper}</span>}</span>
      <ChevronRight className="auth-entry-chevron" aria-hidden="true" />
    </button>
  );
}

export function AuthStatus({ children }: { children?: ReactNode }) {
  return <div className="auth-entry-announcer" role="status" aria-live="polite" aria-atomic="true">{children}</div>;
}

interface AuthPanelProps extends HTMLAttributes<HTMLDivElement> {
  bodyClassName?: string;
  descriptionId?: string;
  footer?: ReactNode;
  header?: ReactNode;
  titleId?: string;
}

export function AuthPanel({
  bodyClassName = 'auth-surface-panel__body',
  children,
  className = '',
  descriptionId,
  footer,
  header,
  role,
  style,
  titleId,
  'aria-modal': ariaModal,
  ...rest
}: AuthPanelProps) {
  const resolvedAriaModal = ariaModal ?? (role === 'dialog' ? true : undefined);

  return (
    <div
      aria-describedby={descriptionId}
      aria-labelledby={titleId}
      aria-modal={resolvedAriaModal}
      className={`auth-surface-panel ${className}`.trim()}
      role={role}
      style={style}
      {...rest}
    >
      {header}
      <div className={bodyClassName}>{children}</div>
      {footer}
    </div>
  );
}

interface AuthTitleBandProps {
  icon?: ReactNode;
  subtitle?: string;
  title: string;
  titleId: string;
}

export function AuthTitleBand({ icon = '🪲', subtitle, title, titleId }: AuthTitleBandProps) {
  return (
    <div className="auth-surface-title-band">
      <div className="auth-surface-title-band__mark" aria-hidden="true">{icon}</div>
      <div className="auth-surface-title-band__copy">
        <h2 id={titleId} className="auth-surface-title-band__title">
          {title}
        </h2>
        {subtitle && (
          <p className="auth-surface-title-band__subtitle">
            {subtitle}
          </p>
        )}
      </div>
    </div>
  );
}

interface AuthNoticeProps extends HTMLAttributes<HTMLDivElement> {
  tone?: 'error' | 'success' | 'warning';
}

export function AuthNotice({
  children,
  className = '',
  role,
  tone = 'warning',
  ...rest
}: AuthNoticeProps) {
  return (
    <div
      className={`auth-surface-notice auth-surface-notice--${tone} ${className}`.trim()}
      role={role ?? (tone === 'error' ? 'alert' : 'status')}
      {...rest}
    >
      <div className="auth-surface-notice__body">
        {children}
      </div>
    </div>
  );
}

interface AuthEmailCodeFormProps {
  codeRequested: boolean;
  email: string;
  code: string;
  hasValidatedInvite: boolean;
  error: string | null;
  pending: boolean;
  status: string;
  inputRef: Ref<HTMLInputElement>;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onChange: (value: string) => void;
}

// Portal-owned form presentation stays separate from provider/session orchestration.
export function AuthEmailCodeForm({ codeRequested, email, code, hasValidatedInvite, error, pending, status, inputRef, onSubmit, onChange }: AuthEmailCodeFormProps) {
  return (
    <form noValidate className="auth-entry-sheet social-login-modal__form" onSubmit={onSubmit}>
      {codeRequested ? (
        <div className="auth-entry-receipt"><Mail aria-hidden="true" /><span>{email}</span></div>
      ) : hasValidatedInvite && <div className="auth-entry-fact"><Check aria-hidden="true" />Invite accepted</div>}
      <div className={`auth-entry-field${codeRequested ? ' auth-entry-code' : ''}`}>
        <label htmlFor={codeRequested ? 'social-login-code' : 'social-login-email'}>{codeRequested ? 'Code' : 'Email'}</label>
        <BeetleInput ref={inputRef} id={codeRequested ? 'social-login-code' : 'social-login-email'}
          name={codeRequested ? 'code' : 'email'} type={codeRequested ? 'text' : 'email'} inputMode={codeRequested ? 'numeric' : 'email'}
          value={codeRequested ? code : email} onChange={(event) => onChange(event.target.value)}
          placeholder={codeRequested ? 'Code' : 'you@example.com'} autoComplete={codeRequested ? 'one-time-code' : 'username'}
          autoCapitalize="none" spellCheck={false} disabled={pending} error={!!error}
          aria-describedby={[error ? 'social-login-error' : '', !codeRequested ? 'social-login-email-helper' : ''].filter(Boolean).join(' ') || undefined} />
      </div>
      {error && <AuthNotice id="social-login-error" tone="error">{error}</AuthNotice>}
      <BeetleButton type="submit" variant="primary" className="auth-entry-action" isLoading={pending} loadingLabel={status || 'Checking'}>
        {codeRequested ? 'Verify code' : 'Send code'}
      </BeetleButton>
    </form>
  );
}
