"""Read the deliberately small YAML subset used by diamond.yaml, without dependencies.

Mappings, scalar lists and block scalar lists only; unsupported syntax fails closed.
This is not a general YAML parser. No parameters have code-side fallback values.
"""
from pathlib import Path
import ast
import math
import re

DEFAULT_PATH = Path(__file__).resolve().parents[2] / 'history/hill-bonding-diamond-2026-10-08/diamond.yaml'


def scalar(value):
    value = value.strip()
    if value in ('true', 'false'):
        return value == 'true'
    if value.startswith('['):
        return [scalar(v) for v in value[1:-1].split(',') if v.strip()]
    if value.startswith(('"', "'")):
        return ast.literal_eval(value)
    if re.fullmatch(r'-?\d+', value):
        return int(value)
    if re.fullmatch(r'-?\d+\.\d+(?:[eE][+-]?\d+)?', value):
        return float(value)
    if any(c in value for c in '{}&*!|>'):
        raise ValueError(f'Unsupported YAML scalar: {value!r}')
    return value


def load_config(path=DEFAULT_PATH):
    lines = []
    for raw in Path(path).read_text().splitlines():
        line = raw.split('#', 1)[0].rstrip()
        if line.strip():
            lines.append((len(line) - len(line.lstrip()), line.strip()))

    def block(pos, indent):
        result = [] if lines[pos][1].startswith('- ') else {}
        while pos < len(lines) and lines[pos][0] == indent:
            content = lines[pos][1]
            pos += 1
            if isinstance(result, list):
                if not content.startswith('- '):
                    raise ValueError('Mixed YAML collection')
                result.append(scalar(content[2:]))
            else:
                key, sep, value = content.partition(':')
                if not sep:
                    raise ValueError(f'Expected YAML mapping: {content}')
                key = str(scalar(key))
                if key in result:
                    raise ValueError(f'Duplicate parameter: {key}')
                if value.strip():
                    result[key] = scalar(value)
                else:
                    if pos >= len(lines) or lines[pos][0] <= indent:
                        raise ValueError(f'Empty mapping: {key}')
                    result[key], pos = block(pos, lines[pos][0])
            if pos < len(lines) and lines[pos][0] > indent:
                raise ValueError('Unsupported indentation')
        return result, pos

    config, pos = block(0, 0)
    if pos != len(lines):
        raise ValueError('Unread YAML data')
    for name in ('rider_split', 'rider_dung_split', 'dung_split'):
        assert math.isclose(sum(config[name].values()), 1), name
    for name in ('fee_on_yield', 'fee_on_cash', 'claim_share_of_riders', 'capital_weight'):
        assert 0 <= config[name] <= 1, name
    assert config['fee_on_cash'] == config['boost']['fee'] == 0
    return config
