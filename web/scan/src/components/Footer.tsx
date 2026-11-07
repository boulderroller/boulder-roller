import CopyButton from '@/components/CopyButton';
import { shortenAddress } from '@/lib/format';
import devnetAddresses from '../../../../protocol/anchor/addresses.devnet.json';

const DEFAULT_PROGRAM_ID = devnetAddresses.programs.boulder_rollers;
const PROGRAM_ID = import.meta.env.VITE_BOULDER_ROLLERS_PROGRAM_ID || DEFAULT_PROGRAM_ID;
const NETWORK = import.meta.env.VITE_SOLANA_NETWORK || 'devnet';
const NETWORK_LABEL = NETWORK === 'mainnet-beta' ? 'Mainnet' : 'Devnet';

export default function Footer() {
  return (
    <footer className="site-footer">
      <div className="site-footer__inner">
        <span className="site-footer__item">
          Program{' '}
          <span className="mono-inline">{shortenAddress(PROGRAM_ID, 6)}</span>
          <CopyButton text={PROGRAM_ID} />
        </span>
        <span className="site-footer__item">{NETWORK_LABEL}</span>
        <a
          className="site-footer__link"
          href="https://boulderroller.xyz"
          target="_blank"
          rel="noreferrer"
        >
          boulderroller.xyz
        </a>
      </div>
    </footer>
  );
}
