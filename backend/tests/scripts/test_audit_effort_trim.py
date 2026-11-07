from types import SimpleNamespace

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

spec = spec_from_file_location(
    "audit_effort_trim",
    Path(__file__).resolve().parents[3] / "tools/corpus/audit_effort_trim.py",
)
audit = module_from_spec(spec)
spec.loader.exec_module(audit)


def test_duplicate_counter_observes_native_returned_claims(monkeypatch):
    # A broken native return must be visible even if requested differences are disjoint.
    returned = iter([[(0, 2000)], [(1000, 3000)]])
    monkeypatch.setattr(
        audit.wp,
        "compute_metrics_in_spans",
        lambda *args: (
            SimpleNamespace(
                tss=2.0,
                duration_s=60,
                moving_time_s=60,
                normalized_power_w=200,
                power_sample_count=60,
                power_sample_coverage_bps=10000,
            ),
            next(returned),
        ),
    )
    values, duplicate_ms = audit.measure_requests(
        None, [(0, 3000)], [(0, 2000), (2000, 3000)]
    )
    assert duplicate_ms == 1000
    assert values == [(2.0, 2.0), (2.0, 2.0)]
