import type { LucideIcon } from 'lucide-react';

interface KpiCardProps {
  icon: LucideIcon;
  label: string;
  value: string | number;
  context?: string;
}

export default function KpiCard({ icon: Icon, label, value, context }: KpiCardProps) {
  return (
    <div className="portal-panel admin-v2-kpi-card">
      <div className="admin-v2-kpi-card__label">
        <Icon size={15} aria-hidden="true" />
        <span>{label}</span>
      </div>
      <div className="admin-v2-kpi-card__value">{value}</div>
      {context ? (
        <div className="admin-v2-kpi-card__context">{context}</div>
      ) : null}
    </div>
  );
}
