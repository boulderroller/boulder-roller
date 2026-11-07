#!/usr/bin/env python3
"""Generate the focused WISSAHICKON 100 urban-repeat policy review pack."""

from __future__ import annotations

import argparse
import html
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_ACTIVITY_ID = "3523251381"
DEFAULT_RUN_ID = "canonical_v2_20260429_210311_85714d"
DEFAULT_DB = Path("/tmp/br_golden_corpus_eval_full_floor.db")
FALLBACK_DB = Path(__file__).parent / "golden_corpus.db"
DEFAULT_OUTPUT = Path(__file__).parent / "policy_reviews" / "3523251381_urban_repeat_policy.html"


@dataclass(frozen=True)
class PolicyCall:
    category: str
    rationale: str


POLICY_BY_SEGMENT_ID: dict[int, PolicyCall] = {
    2767485: PolicyCall("product-visible", "74m sustained trail climb; keep as core climb truth."),
    672938: PolicyCall("product-visible", "42m at 16% wall-style effort; visible as an urban punch climb."),
    651221: PolicyCall("product-visible", "44m at 12% named climb; visible as an urban punch climb."),
    5550552: PolicyCall("product-visible", "27m at 14% short steep repeat; visible only under urban-punch rules."),
    7894730: PolicyCall("product-visible", "26m at 14% short steep repeat; visible only under urban-punch rules."),
    3876380: PolicyCall("benchmark-only", "36m repeat segment; useful for review, too small to tune broad detector thresholds."),
    842002: PolicyCall("benchmark-only", "30m road repeat; local benchmark, not global product-shape truth."),
    25100877: PolicyCall("benchmark-only", "34m moderate repeat; local benchmark, not global product-shape truth."),
    9275817: PolicyCall("benchmark-only", "30m moderate repeat; local benchmark, not global product-shape truth."),
    13511039: PolicyCall("benchmark-only", "26m shallow repeat; local benchmark, not global product-shape truth."),
}

POLICY_ORDER = {"product-visible": 0, "benchmark-only": 1, "noise": 2}


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value))


def fmt(value: Optional[float], digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def load_reference_rows(conn: sqlite3.Connection, activity_id: str) -> list[dict]:
    raw_rows = conn.execute(
        """
        SELECT segment_id, segment_name, COUNT(*) AS effort_count,
               ROUND(AVG(elevation_diff), 1),
               ROUND(AVG(average_grade), 1),
               ROUND(AVG(distance_m), 1)
        FROM strava_segment_efforts
        WHERE activity_id = ?
              AND is_climb = 1
              AND elevation_diff >= 25.0
              AND average_grade >= 2.0
        GROUP BY segment_id, segment_name
        """,
        (activity_id,),
    ).fetchall()
    score_rows = conn.execute(
        """
        SELECT segment_id, segment_name,
               COUNT(*) AS scored_count,
               SUM(CASE WHEN result_type = 'matched' THEN 1 ELSE 0 END) AS matched,
               SUM(CASE WHEN result_type = 'missed' THEN 1 ELSE 0 END) AS missed
        FROM detection_results
        WHERE activity_id = ?
              AND run_id = ?
              AND result_type IN ('matched', 'missed')
        GROUP BY segment_id, segment_name
        """,
        (activity_id, DEFAULT_RUN_ID),
    ).fetchall()
    score_by_id = {row[0]: row for row in score_rows}

    rows: list[dict] = []
    for row in raw_rows:
        segment_id = int(row[0])
        scored = score_by_id.get(segment_id)
        policy = POLICY_BY_SEGMENT_ID.get(
            segment_id,
            PolicyCall("benchmark-only", "Unclassified urban repeat; hold out of broad tuning."),
        )
        rows.append({
            "segment_id": segment_id,
            "segment_name": row[1],
            "effort_count": int(row[2] or 0),
            "elevation_diff": float(row[3] or 0),
            "average_grade": float(row[4] or 0),
            "distance_m": float(row[5] or 0),
            "scored_count": int(scored[2] if scored else 0),
            "matched": int(scored[3] if scored else 0),
            "missed": int(scored[4] if scored else 0),
            "category": policy.category,
            "rationale": policy.rationale,
        })
    return sorted(
        rows,
        key=lambda item: (
            POLICY_ORDER.get(item["category"], 9),
            -item["elevation_diff"],
            item["segment_name"].lower(),
        ),
    )


def load_extra_rows(conn: sqlite3.Connection, activity_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT det_start_s, ROUND(det_vert_m, 1), ROUND(det_grade_pct, 1),
               ROUND(det_distance_m, 1), det_mode
        FROM detection_results
        WHERE activity_id = ?
              AND run_id = ?
              AND result_type = 'extra'
        ORDER BY det_start_s
        """,
        (activity_id, DEFAULT_RUN_ID),
    ).fetchall()
    return [
        {
            "start_s": int(row[0] or 0),
            "vert_m": float(row[1] or 0),
            "grade_pct": float(row[2] or 0),
            "distance_m": float(row[3] or 0),
            "mode": row[4] or "",
        }
        for row in rows
    ]


def load_summary(conn: sqlite3.Connection, activity_id: str) -> dict:
    ride = conn.execute(
        "SELECT name, distance_m, elevation_gain_m FROM rides WHERE activity_id = ?",
        (activity_id,),
    ).fetchone()
    counts = dict(conn.execute(
        """
        SELECT result_type, COUNT(*)
        FROM detection_results
        WHERE activity_id = ? AND run_id = ?
        GROUP BY result_type
        """,
        (activity_id, DEFAULT_RUN_ID),
    ).fetchall())
    return {
        "name": ride[0] if ride else "WISSAHICKON 100",
        "distance_m": float(ride[1] or 0) if ride else 0.0,
        "elevation_gain_m": float(ride[2] or 0) if ride else 0.0,
        "matched": int(counts.get("matched", 0)),
        "missed": int(counts.get("missed", 0)),
        "extras": int(counts.get("extra", 0)),
    }


def render_html(summary: dict, reference_rows: list[dict], extra_rows: list[dict]) -> str:
    product_count = sum(1 for row in reference_rows if row["category"] == "product-visible")
    benchmark_count = sum(1 for row in reference_rows if row["category"] == "benchmark-only")
    product_missed = sum(row["missed"] for row in reference_rows if row["category"] == "product-visible")
    benchmark_missed = sum(row["missed"] for row in reference_rows if row["category"] == "benchmark-only")

    reference_table = "\n".join(
        f"""
        <tr class="{esc(row['category'])}">
          <td>{esc(row['category'])}</td>
          <td>{esc(row['segment_name'])}</td>
          <td>{row['effort_count']}</td>
          <td>{row['matched']}</td>
          <td>{row['missed']}</td>
          <td>{fmt(row['elevation_diff'])}m</td>
          <td>{fmt(row['average_grade'])}%</td>
          <td>{fmt(row['distance_m'])}m</td>
          <td>{esc(row['rationale'])}</td>
        </tr>
        """
        for row in reference_rows
    )
    extras_table = "\n".join(
        f"""
        <tr>
          <td>{row['start_s']}</td>
          <td>{fmt(row['vert_m'])}m</td>
          <td>{fmt(row['grade_pct'])}%</td>
          <td>{fmt(row['distance_m'])}m</td>
          <td>{esc(row['mode'])}</td>
          <td>Nearby urban-hill candidate; review as possible local benchmark, not automatic false positive.</td>
        </tr>
        """
        for row in extra_rows
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>WISSAHICKON 100 Urban-Repeat Policy Review</title>
<style>
  body {{ margin: 0; background: #111827; color: #e5e7eb; font-family: Inter, -apple-system, BlinkMacSystemFont, sans-serif; }}
  main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
  h1, h2 {{ margin: 0 0 12px; }}
  h1 {{ font-size: 28px; }}
  h2 {{ font-size: 18px; margin-top: 28px; }}
  p {{ color: #cbd5e1; line-height: 1.55; }}
  .meta, .decision, .grid, table {{ border: 1px solid #334155; background: #172033; }}
  .meta, .decision {{ padding: 16px; margin: 16px 0; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 1px; background: #334155; }}
  .stat {{ background: #172033; padding: 14px; }}
  .value {{ font-size: 24px; font-weight: 800; }}
  .label {{ color: #94a3b8; font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
  th, td {{ border-bottom: 1px solid #334155; padding: 10px; text-align: left; vertical-align: top; font-size: 13px; }}
  th {{ color: #cbd5e1; background: #1e293b; text-transform: uppercase; letter-spacing: .05em; font-size: 11px; }}
  tr.product-visible td:first-child {{ color: #86efac; font-weight: 800; }}
  tr.benchmark-only td:first-child {{ color: #facc15; font-weight: 800; }}
  code {{ background: #0f172a; border: 1px solid #334155; padding: 2px 5px; }}
</style>
</head>
<body>
<main>
  <h1>WISSAHICKON 100 Urban-Repeat Policy Review</h1>
  <p class="meta">
    Activity <code>{DEFAULT_ACTIVITY_ID}</code> · {esc(summary['name'])} ·
    source run <code>{DEFAULT_RUN_ID}</code>
  </p>
  <div class="grid">
    <div class="stat"><div class="value">{summary['matched']}</div><div class="label">Matched</div></div>
    <div class="stat"><div class="value">{summary['missed']}</div><div class="label">Missed</div></div>
    <div class="stat"><div class="value">{summary['extras']}</div><div class="label">Extras</div></div>
    <div class="stat"><div class="value">{product_count}</div><div class="label">Product-visible refs</div></div>
    <div class="stat"><div class="value">{benchmark_count}</div><div class="label">Benchmark-only refs</div></div>
  </div>

  <section class="decision">
    <h2>Policy Call</h2>
    <p>
      This ride is not a generic detector failure. It is an urban-repeat benchmark case:
      steep 25-44m punch climbs can be product-visible under explicit urban-punch rules,
      while shallow/moderate repeated 25-36m Strava labels should remain benchmark-only
      and should not tune broad canonical_v2 thresholds.
    </p>
    <p>
      Broad holdout scoring should classify this activity as <code>urban_repeat_policy_review</code>.
      Detector changes should target the product-visible misses only. Benchmark-only misses:
      {benchmark_missed}. Product-visible misses: {product_missed}.
    </p>
  </section>

  <h2>Reference Segment Policy</h2>
  <table>
    <thead>
      <tr>
        <th>Policy</th><th>Segment</th><th>Raw repeats</th><th>Matched</th><th>Missed</th>
        <th>Vert</th><th>Grade</th><th>Distance</th><th>Rationale</th>
      </tr>
    </thead>
    <tbody>{reference_table}</tbody>
  </table>

  <h2>Extra Detection Review</h2>
  <p>Extras in this ride are mostly nearby 24-55m urban-hill detections. Treat them as local-review candidates, not automatic false positives.</p>
  <table>
    <thead>
      <tr><th>Start s</th><th>Vert</th><th>Grade</th><th>Distance</th><th>Mode</th><th>Policy note</th></tr>
    </thead>
    <tbody>{extras_table}</tbody>
  </table>
</main>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB if DEFAULT_DB.exists() else FALLBACK_DB))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    summary = load_summary(conn, DEFAULT_ACTIVITY_ID)
    reference_rows = load_reference_rows(conn, DEFAULT_ACTIVITY_ID)
    extra_rows = load_extra_rows(conn, DEFAULT_ACTIVITY_ID)
    conn.close()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html(summary, reference_rows, extra_rows))
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
