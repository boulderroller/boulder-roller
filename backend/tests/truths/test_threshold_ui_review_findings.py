"""Regression guard for the 2026-08-25 Threshold UI review findings."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def source(path: str) -> str:
    return (ROOT / path).read_text()


def test_r1_r2_candidate_is_always_marked_pending_when_it_drives_zones():
    ios_threshold = source("ios/BoulderRoller/App/RiderThreshold.swift")
    ios_sheet = source("ios/BoulderRoller/Surfaces/Avatar/ThresholdSheet.swift")
    ios_zones = source("ios/BoulderRoller/Components/DepthCharts.swift")
    settings = source("web/portal/src/pages/Settings.tsx")

    assert "ThresholdSurfaceValue" in ios_threshold
    assert "isPending" in ios_zones
    assert "· Pending" in ios_zones
    assert "· Pending" in ios_sheet
    assert "· Pending" in settings


def test_r3_failure_or_loading_never_claims_establishing_in_data_core():
    data_core = source("web/portal/src/pages/DataCore.tsx")

    # The ratified Training room replaced the old form-status helper. Guard
    # absence at the rendered metrics boundary, not that helper's old name.
    metrics = data_core.split('aria-label="Training metrics"', 1)[1].split(
        'className="training-words training-words--reads"', 1
    )[0]
    # Previously pinned the legacy fitnessMetrics trio and Loading word; the ratified snapshot uses slots, then absent figures.
    assert "const modelMetrics = snapshot?.fitnessMetrics ?? null" in data_core
    assert "modelMetrics?.tsb == null" in metrics
    assert metrics.count('initialLoading ? <Slot variant="number" />') == 3
    # Values render through the shared estimate mark with the same formatter.
    assert "establishing || !snapshot ? '' : <EstimatedValue measurement={{value: modelMetrics?.ctl" in metrics
    assert "establishing || !snapshot ? '' : <EstimatedValue measurement={{value: modelMetrics?.atl" in metrics
    assert metrics.count("formatValue={formatMetric}") == 2
    assert "? ''" in metrics
    assert "Establishing" not in metrics
    # Loading and failed reads take precedence over the empty-data invitation.
    load_states = data_core.split("{readLoading ? (", 1)[1].split(
        ") : figureEmpty ? (", 1
    )[0]
    assert '<SlotRows count={4} /><span className="sr-only" role="status">Loading</span>' in load_states
    assert ") : !readHasData && readUnavailable ? (" in load_states
    assert 'role="alert"' in load_states
    assert "{readErrorLabel}" in load_states
    assert "<Retry query={readQuery} />" in load_states
    assert "Establishing" not in load_states
    assert "const readUnavailable = readQuery.isError || readQuery.fetchStatus === 'paused'" in data_core
    assert "const readLoading = !readHasData && !readUnavailable" in data_core

    assert "fitnessMetrics?.thresholdTrainingState === 'pending'" in data_core
    truth_word = data_core.split("const truthWord =", 1)[1].split(";", 1)[0]
    assert "readLoading ? <Slot />" in truth_word
    assert "readUnavailable ? readHasData ? 'Last loaded' : ABSENT_VALUE" in truth_word
    assert "thresholdPending && read === 'stress' ? 'Pending'" in truth_word
    assert "Establishing" not in truth_word

    # Only a successful authority read may name the establishing state.
    threshold = data_core.split('aria-labelledby="training-threshold-heading"', 1)[1]
    failure, success = threshold.split("thresholdQuery.isError ? (", 1)[1].split(
        ") : threshold ? (", 1
    )
    assert "formatWatts(null)" in failure
    assert "Establishing" not in failure
    assert "threshold.state === 'establishing' ? (" in success
    loading = threshold.split('aria-busy="true"', 1)[1].split("</div>", 1)[0]
    assert "formatWatts(null)" in loading
    assert "Establishing" not in loading
    assert "fitnessMetrics?.tsb ?? 'Establishing'" not in data_core


def test_r4_r5_failed_threshold_reads_are_visible_and_retryable():
    hook = source("web/portal/src/hooks/useThresholdAuthority.ts")
    settings = source("web/portal/src/pages/Settings.tsx")
    profile = source("web/portal/src/pages/Profile.tsx")
    data_core = source("web/portal/src/pages/DataCore.tsx")
    avatar = source("ios/BoulderRoller/Surfaces/Avatar/AvatarSheet.swift")

    assert "useQuery" in hook
    # Previously pinned Retry; the ratified failure row says Try again and retries the same authority query.
    settings_failure = settings.split("thresholdQuery.isError ? (", 1)[1].split(") : threshold ? (", 1)[0]
    assert "Try again" in settings_failure
    assert "thresholdQuery.refetch()" in settings_failure
    assert "formatWatts(null)" in settings_failure
    assert "Establishing" not in settings_failure
    # Profile — Ground delegates its own Training tab to DataCore; it no
    # longer owns a Threshold row. The failure branch must precede real data
    # and offer a retry of the authority read, with no guessed watts/state.
    assert "activeTab === 'training' && isOwnProfile" in profile
    assert "<Data />" in profile
    threshold = data_core.split('aria-labelledby="training-threshold-heading"', 1)[1]
    failure = threshold.split("thresholdQuery.isError ? (", 1)[1].split(
        ") : threshold ? (", 1
    )[0]
    assert "thresholdQuery.refetch()" in failure
    assert ">Try again</button>" in failure
    assert "formatWatts(null)" in failure
    assert "Establishing" not in failure
    loading = threshold.split('aria-busy="true"', 1)[1].split("</div>", 1)[0]
    assert "formatWatts(null)" in loading
    assert "Establishing" not in loading
    assert "thresholdReadFailed" in avatar
    assert 'CenteredActionRow(label: "Retry")' in avatar
    assert "thresholdDisplay == nil" not in avatar


def test_r6_nullable_current_threshold_uses_the_formatter_path():
    settings = source("web/portal/src/pages/Settings.tsx")

    assert "formatWatts(threshold.currentW)" in settings
    assert "${threshold.currentW} W" not in settings


def test_r7_r10_monday_sealing_preserves_current_without_a_503():
    sql = source("backend/sql/156_threshold_rider_projection.sql")
    ios_threshold = source("ios/BoulderRoller/App/RiderThreshold.swift")

    assert "'sealing_in_progress'" in sql
    assert "Threshold has an overdue unsealed promotion" not in sql
    assert "suppressExpiredPending" in ios_threshold


def test_r8_pending_is_state_grammar_not_a_unit():
    portal_ride = source("web/portal/src/pages/RideViewCore.tsx")
    ios_ride = source("ios/BoulderRoller/Surfaces/Ride/RideDetailView.swift")

    assert "unit: 'Pending'" not in portal_ride
    assert 'unit: ride.thresholdTrainingState == "pending" ? "Pending"' not in ios_ride
    # The Ride page places state beneath the numeral, outside its CAL unit.
    # Previously pinned the CAL markup in RideViewCore; lane C composes the same numeral/state through RidePageLedger.
    ledger = source("web/portal/src/components/ride/RidePageLedger.tsx")
    assert "<RidePageLedger" in portal_ride
    assert "pageCalText={pageCalText}" in portal_ride
    assert "pageCal={pageCal}" in portal_ride
    cal = ledger.split('className="ride-page-cal"', 1)[1].split("</div>", 1)[0]
    numeral, state = cal.split("</strong>", 1)
    assert "{pageCalText}" in numeral
    assert "{pageCal == null ? '' : ' CAL'}" in numeral
    assert "pending" not in numeral.lower()
    assert "<span>{pageCal == null ? 'CAL pending' : ''}</span>" in state
    assert "const pageCalText = pageCal == null ? ABSENT_VALUE : formatInteger(pageCal)" in portal_ride
    assert "· Pending" in ios_ride


def test_r9_feed_and_public_preview_project_the_release_aware_cal_state():
    feed = source("backend/app/feed_contracts.py")
    preview = source("backend/app/public_preview_contracts.py")
    routes = source("backend/app/routes/feed.py")

    assert "thresholdEconomyState" in feed
    assert "thresholdEconomyState" in preview
    assert "_attach_threshold_economy_states" in routes
    assert 'threshold_state == "counted"' in feed


def test_r11_retired_profile_keys_are_ignored_and_units_use_the_live_alias():
    schemas = source("backend/app/schemas.py")
    mobile_api = source("mobile/src/lib/api.ts")

    assert "ignore_retired_profile_keys" in schemas
    assert "units: unitPreference" in mobile_api
    request_body = mobile_api.split(
        "return this.request('PUT', '/users/me', {", 1
    )[1].split("});", 1)[0]
    assert not any(
        line.strip() == "unitPreference," for line in request_body.splitlines()
    )


def test_r12_establishing_never_persists_or_replays_a_guessed_denominator():
    store = source("backend/app/services/ride_projection_store.py")
    replay = source("backend/app/services/replay_service.py")
    processor = source("backend/app/services/ride_processor.py")

    assert "user_ftp_w: Optional[int]" in store
    assert 'ftp_watts") or 200' not in replay
    assert "threshold_training_w or 200" not in processor


def test_r13_threshold_authority_uses_shared_query_cache_and_invalidation():
    hook = source("web/portal/src/hooks/useThresholdAuthority.ts")
    keys = source("web/portal/src/lib/queryKeys.ts")
    upload = source("web/portal/src/hooks/queries/useUploadRide.ts")

    assert "useQuery" in hook
    assert "setTimeout" not in hook
    assert "threshold" in keys
    assert "queryKeys.threshold" in upload


def test_r14_dead_projection_work_is_removed():
    sql = source("backend/sql/156_threshold_rider_projection.sql")
    schemas = source("backend/app/schemas.py")
    metrics = source("backend/app/services/ride_metrics.py")

    assert "latest_release" not in sql
    assert "ThresholdLatestRelease" not in schemas
    assert "def calculate_zone_distribution" not in metrics
