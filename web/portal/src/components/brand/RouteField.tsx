import { useId } from 'react';
import { LeaderboardStrip, ReceiptStrip } from './BrandStrips';

const leaderboardRows = [
  ['1', 'M. Reyes', '5:42'],
  ['2', 'J. Allen', '5:51'],
  ['3', 'You', '6:03'],
];

export default function RouteField() {
  const routeFieldId = useId().replace(/:/g, '');
  const gradientId = `${routeFieldId}-route-gradient`;
  const shadowId = `${routeFieldId}-route-shadow`;

  return (
    <div className="br-route-field" aria-hidden="true">
      <svg className="br-route-field__route access-entry-route" viewBox="0 0 820 520" role="img">
        <defs>
          <linearGradient id={gradientId} x1="132" y1="404" x2="700" y2="84" gradientUnits="userSpaceOnUse">
            <stop stopColor="#177865" />
            <stop offset="0.55" stopColor="#1687d9" />
            <stop offset="1" stopColor="#d6a629" />
          </linearGradient>
          <filter id={shadowId} x="-10%" y="-10%" width="120%" height="120%">
            <feDropShadow dx="0" dy="18" stdDeviation="22" floodColor="#101814" floodOpacity="0.12" />
          </filter>
        </defs>
        <path className="br-route-field__terrain br-route-field__terrain--a" d="M34 420 C160 370 232 446 348 390 C474 328 530 224 790 176" />
        <path className="br-route-field__terrain br-route-field__terrain--b" d="M18 252 C118 180 246 242 360 194 C478 144 612 124 804 58" />
        <path className="br-route-field__terrain br-route-field__terrain--c" d="M74 494 C230 458 304 506 424 456 C548 406 642 326 796 312" />
        <path className="br-route-field__path" d="M118 410 C196 318 270 366 324 282 C380 194 452 220 506 150 C558 82 642 88 708 62" filter={`url(#${shadowId})`} stroke={`url(#${gradientId})`} />
        <path className="br-route-field__climb" d="M506 150 C558 82 642 88 708 62" />
        <circle className="br-route-field__node br-route-field__node--a" cx="118" cy="410" r="7" />
        <circle className="br-route-field__node br-route-field__node--b" cx="324" cy="282" r="7" />
        <circle className="br-route-field__node br-route-field__node--c" cx="506" cy="150" r="7" />
        <circle className="br-route-field__node br-route-field__node--d" cx="708" cy="62" r="7" />
      </svg>

      <ReceiptStrip
        className="br-route-field__receipt br-route-field__receipt--cal access-entry-receipt"
        variant="cal"
        label="Counted CAL"
        value="+881"
      />

      <ReceiptStrip
        className="br-route-field__receipt br-route-field__receipt--record access-entry-receipt"
        variant="record"
        label="Ride"
        value="Ready"
      />

      <LeaderboardStrip
        className="br-route-field__board access-entry-board"
        title="Manayunk Wall"
        subtitle="Leaderboard"
        rows={leaderboardRows.map(([rank, rider, time]) => ({ rank, rider, time, key: rank }))}
      />

      <div className="br-route-field__elevation">
        <svg viewBox="0 0 360 92" preserveAspectRatio="none">
          <path d="M0 72 C34 66 52 52 78 55 C108 58 124 28 152 30 C190 33 204 72 238 68 C276 62 288 18 322 22 C342 24 352 16 360 12" />
        </svg>
      </div>
    </div>
  );
}
