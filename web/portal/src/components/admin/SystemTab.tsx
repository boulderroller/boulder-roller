import ControlPanel from './ControlPanel';
import EpochPanel from './EpochPanel';
import AuditLog from './AuditLog';
import StravaPanel from './StravaPanel';

export default function SystemTab() {
  return (
    <div className="admin-v2-tab-surface">
      <div className="admin-v2-panel-grid admin-v2-panel-grid--two">
        <ControlPanel />
        <EpochPanel />
      </div>

      <div className="admin-v2-panel-grid admin-v2-panel-grid--strava">
        <StravaPanel />
        <div className="admin-v2-panel-grid__wide">
          <AuditLog />
        </div>
      </div>
    </div>
  );
}
