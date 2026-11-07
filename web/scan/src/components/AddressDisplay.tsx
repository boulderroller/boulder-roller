import { Link } from 'react-router-dom';
import CopyButton from '@/components/CopyButton';
import { getAddressLabel } from '@/lib/labels';
import { shortenAddress } from '@/lib/format';

type AddressDisplayProps = {
  address: string;
  /** Number of chars to show on each side of the ellipsis. */
  chars?: number;
  /** If true, render as a link to the account page. */
  link?: boolean;
};

/**
 * Renders an address with its protocol label (if known) + shortened address + copy button.
 * Example: "Treasury (3boU...hSra)" or just "3boU...hSra" for unknown addresses.
 */
export default function AddressDisplay({ address, chars = 4, link = true }: AddressDisplayProps) {
  const label = getAddressLabel(address);
  const short = shortenAddress(address, chars);

  const addressContent = link ? (
    <Link to={`/account/${address}`} className="mono-link">
      {short}
    </Link>
  ) : (
    <span className="mono-inline">{short}</span>
  );

  return (
    <span className="addr-group">
      {label ? (
        <>
          <span className="addr-label" title={address}>{label}</span>
          {' '}
          <span className="addr-short">(</span>
          {addressContent}
          <span className="addr-short">)</span>
        </>
      ) : (
        addressContent
      )}
      <CopyButton text={address} />
    </span>
  );
}
