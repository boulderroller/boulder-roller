"""Resolve the same committed keeper assets in a checkout and the API image."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGED = Path(__file__).resolve().parents[1] / "stage1_runtime"
ORACLE_TOOLS = (PACKAGED if PACKAGED.is_dir() else ROOT) / "tools"
IDL = PACKAGED / "idl/boulder_rollers.json" if PACKAGED.is_dir() else ROOT / "protocol/anchor/idl/boulder_rollers.json"
