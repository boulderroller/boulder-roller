import { Link, useLocation } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import type { ReactNode } from 'react';

export function useClimbPanelPath() {
  const location = useLocation();
  return (panel?: string) => {
    const search = new URLSearchParams(location.search);
    if (panel) search.set('climbView', panel);
    else search.delete('climbView');
    return `${location.pathname}${search.size ? `?${search}` : ''}`;
  };
}

export function ClimbNavigationRow({ to, label, value }: { to: string; label: string; value?: ReactNode }) {
  return <Link className="climb-navigation-row" to={to}><span>{label}</span>{value != null && <span className="climb-row-value">{value}</span>}<ChevronRight size={15} className="climb-chevron" aria-hidden="true" /></Link>;
}
