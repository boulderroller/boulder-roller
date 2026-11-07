import { ArrowUpRight } from 'lucide-react';
import type { Scenario } from './scenario';
import type { ExampleCal, ExampleEconomics } from './v8Example';

export function V8CalAmount({ value, pending = false }: { value: ExampleCal; pending?: boolean }) {
  return <span className="v8-cal-amount"><span className="v8-value" data-pending={pending || undefined}><span aria-hidden={pending || undefined}>{value.amount}<small>CAL</small></span></span><span className="v8-cal-state">{pending ? 'Loading' : value.state === 'pending' ? 'Pending' : 'Counted'}</span></span>;
}

export function V8Economics({ scenario, economics, pending, onClimb }: { scenario: Scenario; economics: ExampleEconomics; pending: boolean; onClimb: (id: string) => void }) {
  return <section className="v8-economics-room" aria-label="CAL and tribute">
    <header><h2>CAL & tribute</h2><span className="v8-example-label">Illustrative economics</span></header>
    <div className="v8-cal-flow">
      <div className="v8-flow-origin"><span>Ride</span><strong>{scenario.ride.title}</strong></div>
      <div className="v8-flow-outcomes">
        <section className="v8-flow-rider"><div><span>Ride CAL</span><strong>{scenario.ride.rider?.displayName ?? 'Rider'}</strong></div><V8CalAmount value={economics.riderCal} pending={pending}/></section>
        <section className="v8-flow-tribute"><header><h3>Climb tribute</h3><span>Vault destinations</span></header>
          {economics.tributes.map(tribute => <div className="v8-tribute-row" key={tribute.climbId}><div className="v8-tribute-climb"><button onClick={() => onClimb(tribute.climbId)} aria-label={`Analyze ${tribute.climbName}`}><strong>{tribute.climbName}</strong><ArrowUpRight size={13}/></button><span>Vault</span></div><V8CalAmount value={tribute.cal} pending={pending}/></div>)}
        </section>
      </div>
    </div>
    <p className="v8-cal-explanation">The rider receives the full Ride CAL. Each climb contributes tribute to its Vault separately.</p>
    <details className="v8-measurement-details"><summary>About CAL & tribute</summary><p>Ride CAL follows the ride’s TSS. Each eligible climb’s tribute follows the TSS measured within that climb. Tribute does not reduce the rider’s CAL.</p><p>These amounts, pending states and Vault destinations are illustrative. They are not earnings or verified Vault matches from this recording. CAL is not a measurement of dietary calories.</p></details>
  </section>;
}
