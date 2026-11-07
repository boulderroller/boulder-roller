import * as React from 'react';
import { cn } from '../ui/utils';

type DivProps = React.HTMLAttributes<HTMLDivElement>;

export function PortalPage({ className, ...props }: DivProps) {
  return <div className={cn('portal-page', className)} {...props} />;
}

export function PortalFrame({ className, ...props }: DivProps) {
  return <div className={cn('portal-frame', className)} {...props} />;
}

export function PortalGrid({ className, ...props }: DivProps) {
  return <div className={cn('portal-grid', className)} {...props} />;
}

export function PortalMain({ className, ...props }: DivProps) {
  return <main className={cn('portal-main', className)} {...props} />;
}

export const PortalRail = React.forwardRef<HTMLDivElement, DivProps>(
  ({ className, ...props }, ref) => (
    <aside ref={ref} className={cn('portal-rail', className)} {...props} />
  ),
);
PortalRail.displayName = 'PortalRail';

export function PortalStack({ className, ...props }: DivProps) {
  return <div className={cn('portal-stack', className)} {...props} />;
}

type PortalPanelProps = DivProps & {
  interactive?: boolean;
};

export function PortalPanel({ className, interactive = false, ...props }: PortalPanelProps) {
  return (
    <div
      className={cn('portal-panel', interactive && 'portal-panel--interactive', className)}
      {...props}
    />
  );
}

type PortalButtonPanelProps = React.ButtonHTMLAttributes<HTMLButtonElement>;

export function PortalButtonPanel({ className, type = 'button', ...props }: PortalButtonPanelProps) {
  return (
    <button
      type={type}
      className={cn('portal-panel portal-panel--button portal-panel--interactive', className)}
      {...props}
    />
  );
}

type PortalPanelHeaderProps = DivProps & {
  title: React.ReactNode;
  meta?: React.ReactNode;
};

export function PortalPanelHeader({ className, title, meta, children, ...props }: PortalPanelHeaderProps) {
  return (
    <div className={cn('portal-panel__header', className)} {...props}>
      <div className="portal-panel__title">{title}</div>
      {meta ? <div className="portal-panel__meta">{meta}</div> : null}
      {children}
    </div>
  );
}

export function PortalPanelBody({ className, ...props }: DivProps) {
  return <div className={cn('portal-panel__body', className)} {...props} />;
}

export function PortalList({ className, ...props }: DivProps) {
  return <div className={cn('portal-list', className)} {...props} />;
}

type PortalListItemProps = DivProps & {
  asButton?: false;
};

type PortalListButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  asButton: true;
};

export function PortalListItem(props: PortalListItemProps | PortalListButtonProps) {
  if ('asButton' in props && props.asButton) {
    const { className, asButton: _asButton, type = 'button', ...buttonProps } = props;
    return (
      <button
        type={type}
        className={cn('portal-list__item portal-list__item--button', className)}
        {...buttonProps}
      />
    );
  }

  const { className, ...divProps } = props;
  return <div className={cn('portal-list__item', className)} {...divProps} />;
}

type PortalMetricProps = {
  value: React.ReactNode;
  label: React.ReactNode;
  align?: 'left' | 'center' | 'right';
  accent?: boolean;
  valueFamily?: 'sans' | 'mono';
};

export function PortalMetric({
  value,
  label,
  align = 'left',
  accent = false,
  valueFamily = 'mono',
}: PortalMetricProps) {
  return (
    <div className={cn('portal-metric', `portal-metric--${align}`, accent && 'portal-metric--accent')}>
      <div className={cn('portal-metric__value', `portal-metric__value--${valueFamily}`)}>{value}</div>
      <div className="portal-metric__label">{label}</div>
    </div>
  );
}

type PortalEmptyStateProps = DivProps & {
  title: React.ReactNode;
  description?: React.ReactNode;
  icon?: React.ReactNode;
  action?: React.ReactNode;
};

export function PortalEmptyState({ className, title, description, icon, action, ...props }: PortalEmptyStateProps) {
  return (
    <div className={cn('portal-empty', className)} {...props}>
      {icon ? <div className="portal-empty__icon">{icon}</div> : null}
      <h3 className="portal-empty__title">{title}</h3>
      {description ? <p className="portal-empty__description">{description}</p> : null}
      {action ? <div className="portal-empty__action">{action}</div> : null}
    </div>
  );
}

type PortalTruthPillProps = {
  children: React.ReactNode;
  tone?: 'verified' | 'muted' | 'warning';
};

export function PortalTruthPill({ children, tone = 'muted' }: PortalTruthPillProps) {
  return <span className={cn('portal-truth-pill', `portal-truth-pill--${tone}`)}>{children}</span>;
}

export { StateRow } from './FailureSpecies';
