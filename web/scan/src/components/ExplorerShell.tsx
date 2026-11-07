import '@/styles/observatory.css';
import { FormEvent, ReactNode, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom';
import Footer from '@/components/Footer';
import { getIndexerHealth, resolveUsernameAccount } from '@/lib/api';
import { formatCount, formatStatus, looksLikePubkey } from '@/lib/format';
import { classifySearchInput, isUsernameSearch, searchFailureMessage, searchTarget } from '@/lib/search';

type ExplorerShellProps = {
  children: ReactNode;
};

const NAV_ITEMS = [
  { to: '/', label: 'Observatory' },
];

const STALE_LAG_THRESHOLD_SLOTS = 150;

function numericLag(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatSlotLag(value: unknown): string {
  const lag = numericLag(value);
  if (lag === null) return '—';
  return `${formatCount(lag)} slot${lag === 1 ? '' : 's'}`;
}

function livenessStatusLabel(status: string | undefined, isLagging: boolean): string {
  if (isLagging || status === 'lagging') return 'Lagging';
  if (status === 'error') return 'Error';
  return 'Live';
}

export default function ExplorerShell({ children }: ExplorerShellProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const [value, setValue] = useState('');
  const [validationMessage, setValidationMessage] = useState('');
  const [isResolvingSearch, setIsResolvingSearch] = useState(false);

  const healthQuery = useQuery({
    queryKey: ['indexer-health'],
    queryFn: getIndexerHealth,
    staleTime: 15_000,
    refetchInterval: 30_000,
    refetchIntervalInBackground: true,
    retry: 1,
  });

  const helperText = useMemo(() => {
    if (location.pathname.startsWith('/climb/') || location.pathname.startsWith('/vault/')) {
      return 'Search another climb, rider, account, transaction, or pasted BoulderScan link.';
    }
    if (location.pathname.startsWith('/tx/')) {
      return 'Search another transaction, climb, rider, account, or pasted explorer link.';
    }
    if (location.pathname.startsWith('/account/')) {
      return 'Search another account, rider, climb, transaction, or pasted explorer link.';
    }
    return 'Paste a BoulderScan link or enter any climb id, rider, account, or transaction.';
  }, [location.pathname]);

  const maxLag = numericLag(healthQuery.data?.lag_slots);
  const isLagging =
    healthQuery.data?.status === 'lagging' ||
    (maxLag !== null && maxLag > STALE_LAG_THRESHOLD_SLOTS);
  const healthTone = healthQuery.data
    ? (isLagging || healthQuery.data.status === 'error' ? 'warn' : 'ok')
    : 'muted';

  const slotLagLabel = useMemo(() => {
    return formatSlotLag(healthQuery.data?.lag_slots);
  }, [healthQuery.data?.lag_slots]);

  const accountLagLabel = useMemo(() => {
    return formatSlotLag(healthQuery.data?.account_lag_slots);
  }, [healthQuery.data?.account_lag_slots]);

  const txLagLabel = useMemo(() => {
    return formatSlotLag(healthQuery.data?.tx_lag_slots);
  }, [healthQuery.data?.tx_lag_slots]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const match = classifySearchInput(value);

    if (!match) {
      setValidationMessage('Enter a climb id, rider, account, transaction, or BoulderScan URL.');
      return;
    }

    setValidationMessage('');
    setIsResolvingSearch(true);

    try {
      if (isUsernameSearch(match)) {
        const resolution = await resolveUsernameAccount(match.value);
        if (!looksLikePubkey(resolution.pubkey)) {
          throw new Error('That rider username did not resolve to a valid public wallet address.');
        }
        navigate(`/account/${resolution.pubkey}`);
        setValue('');
        return;
      }

      const target = searchTarget(value);
      if (!target) {
        throw new Error('Search target was not recognized.');
      }

      navigate(target);
      setValue('');
    } catch (error) {
      setValidationMessage(searchFailureMessage(error, match));
    } finally {
      setIsResolvingSearch(false);
    }
  }

  if (location.pathname === '/' || location.pathname.startsWith('/tx/') || location.pathname.startsWith('/proof/') || location.pathname.startsWith('/account/') || location.pathname.startsWith('/climb/')) return <div className={`week-shell ${location.pathname !== '/' ? 'climb-shell' : ''}`}>
    <a href="#main-content" className="skip-link">Skip to content</a>
    <header className="week-shell__header"><Link to="/" className="week-brand"><i aria-hidden="true" />BoulderScan</Link><div><span>Devnet</span><a href="https://boulderroller.xyz">Boulder Roller</a></div></header>
    <main id="main-content">{children}</main>
  </div>;

  return (
    <div className="app-shell">
      <a href="#main-content" className="skip-link">Skip to content</a>
      <div className="backdrop-grid" />
      <header className="site-header">
        <div className="site-header__inner">
          <div className="brand-block">
            <Link to="/" className="brand-mark">
              <span className="brand-mark__kicker">Boulder</span>
              <span className="brand-mark__name">Scan</span>
            </Link>
          </div>
          <div className="site-header__actions">
            <nav className="site-nav" aria-label="Primary">
              {NAV_ITEMS.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) => `site-nav__link${isActive ? ' is-active' : ''}`}
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
            <a
              className="status-pill"
              href="https://boulderroller.xyz"
              target="_blank"
              rel="noreferrer"
            >
              BoulderRoller
            </a>
          </div>
        </div>
        <div className="search-band">
          <form className="search-band__form" onSubmit={handleSubmit}>
            <div className="search-band__form-header">
              <div>
                <label className="search-label" htmlFor="scan-search">
                  Universal Lookup
                </label>
                <p className="search-band__caption">
                  Climb ids, rider usernames, wallet addresses, signatures, and BoulderScan links.
                </p>
              </div>
              <div className="liveness-strip" aria-label="Indexer health">
                {healthQuery.data ? (
                  <div
                    className={`liveness-chip liveness-chip--${healthTone}`}
                    title={`Stream: ${healthQuery.data.stream_connected ? 'connected' : 'polling'} · Max lag: ${slotLagLabel} · Account lag: ${accountLagLabel} · Tx lag: ${txLagLabel} · Head: ${formatCount(healthQuery.data.last_indexed_slot)}`}
                  >
                    <span className="liveness-chip__dot" />
                    <strong>Indexer {livenessStatusLabel(healthQuery.data.status, isLagging)}</strong>
                    <span className="liveness-chip__meta">{slotLagLabel}</span>
                  </div>
                ) : (
                  <div className={`liveness-chip liveness-chip--${healthQuery.isError ? 'warn' : 'muted'}`}>
                    <span className="liveness-chip__dot" />
                    <strong>{healthQuery.isError ? 'Unavailable' : 'Loading...'}</strong>
                  </div>
                )}
              </div>
            </div>
            <div className="search-band__input-row">
              <input
                id="scan-search"
                className="search-input"
                value={value}
                onChange={(event) => {
                  setValue(event.target.value);
                  if (validationMessage) setValidationMessage('');
                }}
                placeholder="climb:42, @rider, wallet, tx, or link"
              />
              <button type="submit" className="search-button" disabled={isResolvingSearch}>
                {isResolvingSearch ? 'Resolving...' : 'Search'}
              </button>
            </div>
            <p className={`search-helper${validationMessage ? ' search-helper--error' : ''}`}>
              {validationMessage || helperText}
            </p>
          </form>
        </div>
      </header>
      <main id="main-content" className="page-shell">{children}</main>
      <Footer />
    </div>
  );
}
