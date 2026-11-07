import { Link } from 'react-router-dom';
import { formatFixed } from '../../lib/formatters';

const DOCS_URL = 'https://docs.boulderroller.xyz/';
const PRIVACY_SETTINGS_PATH = '/settings?tab=privacy';

type PortalUtilityLinksProps =
  | { placement: 'rail'; onNavigate?: never }
  | { placement: 'account'; onNavigate: () => void };

export function PortalUtilityLinks(props: PortalUtilityLinksProps) {
  const isAccountPlacement = props.placement === 'account';
  const onNavigate = isAccountPlacement ? props.onNavigate : undefined;
  const linkRole = isAccountPlacement ? 'menuitem' : undefined;
  const links = (
    <div className="portal-utility-links__row">
      <a className="portal-utility-links__link" href={DOCS_URL} role={linkRole} onClick={onNavigate}>Docs</a>
      <span className="portal-utility-links__separator" aria-hidden="true">·</span>
      <a className="portal-utility-links__link" href="https://docs.boulderroller.xyz/open-data" role={linkRole} onClick={onNavigate}>Open climb data</a>
      <Link className="portal-utility-links__link" to={PRIVACY_SETTINGS_PATH} role={linkRole} onClick={onNavigate}>Privacy settings</Link>
    </div>
  );

  if (isAccountPlacement) {
    return (
      <div className="portal-account-utility-strip" role="group" aria-label="Account utilities">
        {links}
      </div>
    );
  }

  const currentYear = new Date().getFullYear();
  return (
    <footer className="feed-rail-footer" aria-label="Boulder Roller">
      <nav aria-label="Utility links">{links}</nav>
      <small className="feed-rail-footer__copyright">© {formatFixed(currentYear, 0)} Boulder Roller</small>
    </footer>
  );
}
