"""Tim's two estimate-copy slots must agree on both rider clients."""

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def copy_entries(source: str) -> dict[str, tuple[str, str]]:
    # Both maps deliberately use literal keys and two literal strings. Decode
    # escapes rather than comparing spellings (e.g. an escaped apostrophe).
    string = r'''(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')'''
    entry = re.compile(
        rf"(?P<key>{string}|[A-Za-z_]\w*)\s*:\s*\[\s*"
        rf"(?P<first>{string})\s*,\s*(?P<second>{string})\s*\]"
    )
    matches = list(entry.finditer(source))
    result = {}
    for match in matches:
        key = match['key']
        key = ast.literal_eval(key) if key[0] in "\"'" else key
        assert key not in result, f"Duplicate basis: {key}"
        result[key] = (ast.literal_eval(match['first']), ast.literal_eval(match['second']))
    assert result, "Estimate copy map must contain literal two-line entries"
    return result


def test_estimate_copy_keys_and_both_lines_match_portal():
    swift_path = ROOT / 'ios/BoulderRoller/Design/EstimateCopy.swift'
    assert swift_path.exists(), 'iOS is missing the shared basis-copy map'
    swift = swift_path.read_text().split('static let slots:', 1)[1].split('\n    ]', 1)[0]
    portal = (ROOT / 'web/portal/src/lib/estimateCopy.ts').read_text()
    portal = portal.split('export const estimateCopy:', 1)[1].split('\n};', 1)[0]
    assert copy_entries(swift) == copy_entries(portal)
