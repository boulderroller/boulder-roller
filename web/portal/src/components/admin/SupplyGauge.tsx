import { PortalPanel, PortalPanelBody, PortalPanelHeader } from '../portal/PortalSpine';
import { formatCompactBaseUnits, isPositiveBaseUnits } from '../../lib/tokenAmounts';
import { ABSENT_VALUE, formatPercent } from '../../lib/formatters';

type AllocationTone = 'community' | 'treasury' | 'team' | 'investor' | 'pol';

interface Allocation {
  label: string;
  capBaseUnits: string;
  mintedBaseUnits: string;
  tone: AllocationTone;
}

const DEFAULT_ALLOCATIONS: Allocation[] = [
  { label: 'Community', capBaseUnits: '400000000000000000', mintedBaseUnits: '0', tone: 'community' },
  { label: 'Treasury', capBaseUnits: '250000000000000000', mintedBaseUnits: '0', tone: 'treasury' },
  { label: 'Team', capBaseUnits: '200000000000000000', mintedBaseUnits: '0', tone: 'team' },
  { label: 'Investor', capBaseUnits: '100000000000000000', mintedBaseUnits: '0', tone: 'investor' },
  { label: 'POL', capBaseUnits: '50000000000000000', mintedBaseUnits: '0', tone: 'pol' },
];

interface SupplyGaugeProps {
  supply: {
    maxSupplyBaseUnits: string;
    totalMintedBaseUnits: string;
    protocolBurnedBaseUnits: string;
    circulatingSupplyBaseUnits: string | null;
    communityMintedBaseUnits: string;
    communityCapBaseUnits: string;
    treasuryMintedBaseUnits: string;
    treasuryCapBaseUnits: string;
    teamMintedBaseUnits: string;
    teamCapBaseUnits: string;
    investorMintedBaseUnits: string;
    investorCapBaseUnits: string;
    polMintedBaseUnits: string;
    polCapBaseUnits: string;
  } | null;
}

function percentOf(valueBaseUnits: string, capBaseUnits: string): number {
  try {
    const value = BigInt(valueBaseUnits);
    const cap = BigInt(capBaseUnits);
    if (value < 0n || cap <= 0n) return 0;
    const hundredthsOfPercent = (value * 10_000n) / cap;
    return Math.min(Number(hundredthsOfPercent) / 100, 100);
  } catch {
    return 0;
  }
}

export default function SupplyGauge({ supply }: SupplyGaugeProps) {
  const maxSupplyBaseUnits = supply?.maxSupplyBaseUnits ?? '1000000000000000000';
  const totalMintedBaseUnits = supply?.totalMintedBaseUnits ?? '0';
  const protocolBurnedBaseUnits = supply?.protocolBurnedBaseUnits ?? '0';
  const circulatingSupplyBaseUnits = supply?.circulatingSupplyBaseUnits ?? null;
  const mintedPct = percentOf(totalMintedBaseUnits, maxSupplyBaseUnits);

  const allocations: Allocation[] = supply
    ? [
        { label: 'Community', capBaseUnits: supply.communityCapBaseUnits, mintedBaseUnits: supply.communityMintedBaseUnits, tone: 'community' },
        { label: 'Treasury', capBaseUnits: supply.treasuryCapBaseUnits, mintedBaseUnits: supply.treasuryMintedBaseUnits, tone: 'treasury' },
        { label: 'Team', capBaseUnits: supply.teamCapBaseUnits, mintedBaseUnits: supply.teamMintedBaseUnits, tone: 'team' },
        { label: 'Investor', capBaseUnits: supply.investorCapBaseUnits, mintedBaseUnits: supply.investorMintedBaseUnits, tone: 'investor' },
        { label: 'POL', capBaseUnits: supply.polCapBaseUnits, mintedBaseUnits: supply.polMintedBaseUnits, tone: 'pol' },
      ]
    : DEFAULT_ALLOCATIONS;

  return (
    <PortalPanel className="admin-v2-supply-panel">
      <PortalPanelHeader title="DUNG Supply" meta="Minted" />
      <PortalPanelBody className="admin-v2-supply">
        <div className="admin-v2-supply__summary">
          <strong>{formatCompactBaseUnits(totalMintedBaseUnits, 9)}</strong>
          <span>/ {formatCompactBaseUnits(maxSupplyBaseUnits, 9)} minted</span>
        </div>

        {isPositiveBaseUnits(protocolBurnedBaseUnits) ? (
          <div className="admin-v2-supply__subline">
            {formatCompactBaseUnits(protocolBurnedBaseUnits, 9)} protocol burns /{' '}
            {circulatingSupplyBaseUnits == null
              ? ABSENT_VALUE
              : formatCompactBaseUnits(circulatingSupplyBaseUnits, 9)} circulating
          </div>
        ) : null}

        <progress
          className="admin-v2-supply__track admin-v2-supply__track--total"
          value={mintedPct}
          max={100}
          aria-label="Total DUNG minted"
        >
          {formatPercent(mintedPct, 0)}
        </progress>

        <div className="admin-v2-supply__allocations">
          {allocations.map((allocation) => {
            const pct = percentOf(allocation.mintedBaseUnits, allocation.capBaseUnits);
            return (
              <div key={allocation.label} className="admin-v2-supply__allocation">
                <div className="admin-v2-supply__allocation-topline">
                  <span className="admin-v2-color-swatch" data-tone={allocation.tone} />
                  <span>{allocation.label}</span>
                  <em>
                    {formatCompactBaseUnits(allocation.mintedBaseUnits, 9)} /{' '}
                    {formatCompactBaseUnits(allocation.capBaseUnits, 9)}
                  </em>
                </div>
                <progress
                  className="admin-v2-supply__track admin-v2-supply__track--thin"
                  data-tone={allocation.tone}
                  value={pct}
                  max={100}
                  aria-label={`${allocation.label} allocation minted`}
                >
                  {formatPercent(pct, 0)}
                </progress>
              </div>
            );
          })}
        </div>
      </PortalPanelBody>
    </PortalPanel>
  );
}
