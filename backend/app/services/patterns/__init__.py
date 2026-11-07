"""
Pattern detection services for tile-based attestation.

Patterns are effort shapes detected from tile samples, replacing
traditional segment-based competition.

Pattern Types:
- ClimbPattern: Sustained vertical gain efforts
- SteadyPattern: Z2-Z3 aerobic intensity blocks
- ExplorationPattern: New tile discovery and night riding
"""

from .climb import ClimbPatternDetector, ClimbPattern
from .exploration import (
    ExplorationPattern,
    ExplorationPatternDetector,
    ExplorationConfig,
    detect_exploration_pattern,
)
from .steady import SteadyPatternDetector, SteadyConfig

__all__ = [
    # Climb
    "ClimbPatternDetector",
    "ClimbPattern",
    # Steady
    "SteadyPatternDetector",
    "SteadyConfig",
    # Exploration
    "ExplorationPattern",
    "ExplorationPatternDetector",
    "ExplorationConfig",
    "detect_exploration_pattern",
]
