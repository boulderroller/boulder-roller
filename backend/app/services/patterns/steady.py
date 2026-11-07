"""
SteadyPattern detection algorithm.

Detects sustained aerobic efforts in Z2-Z3 intensity band from power or heart rate data.

Pattern Criteria:
- Duration >= 20 min (configurable)
- Intensity stays in Z2-Z3 band (60-85% of FTP or threshold HR)
- Variability below threshold (coefficient of variation < 0.15)

Selection: Longest duration or highest workload
"""

from __future__ import annotations

import logging
import statistics
import uuid
from dataclasses import dataclass
from typing import List, Optional

from app.models.patterns import SteadyPattern

logger = logging.getLogger(__name__)


@dataclass
class SteadyConfig:
    """Configuration for SteadyPattern detection."""

    # Minimum duration for a valid steady effort (seconds)
    window_min_s: int = 1200  # 20 minutes

    # Intensity band as fraction of FTP (Z2-Z3 range)
    intensity_min: float = 0.60  # Z2 lower bound
    intensity_max: float = 0.85  # Z3 upper bound

    # Maximum coefficient of variation for power/HR
    variability_max: float = 0.15  # CV = std_dev / mean

    # Minimum percentage of samples that must be in-band
    in_band_threshold: float = 0.80  # 80% of samples

    # For HR-based detection
    hr_z2_min_pct: float = 0.60  # Z2 as % of threshold HR
    hr_z3_max_pct: float = 0.85  # Z3 as % of threshold HR

    # For normalized power calculation (exponential moving average)
    np_window_s: int = 30  # 30-second rolling average


class SteadyPatternDetector:
    """
    Detects SteadyPattern from tile samples with power or heart rate data.

    Algorithm:
    1. Calculate intensity for each sample (power/FTP or HR zones)
    2. Find sliding windows where intensity stays in Z2-Z3 band
    3. Check variability (CV of power/HR) within window
    4. Select best window (longest or highest workload)
    5. Return SteadyPattern or None
    """

    def __init__(self, config: Optional[SteadyConfig] = None):
        """
        Initialize the detector with configuration.

        Args:
            config: Optional configuration object. Uses defaults if not provided.
        """
        self.config = config or SteadyConfig()

    def detect(
        self,
        tile_samples: List[dict],
        user_ftp: Optional[int] = None,
        user_threshold_hr: Optional[int] = None,
        wallet: str = "",
        activity_id: Optional[uuid.UUID] = None,
    ) -> Optional[SteadyPattern]:
        """
        Detect the best SteadyPattern from tile samples.

        Args:
            tile_samples: List of tile sample dicts with keys:
                - t: int (seconds since ride start)
                - power_w: int (optional)
                - hr_bpm: int (optional)
            user_ftp: User's Functional Threshold Power (watts)
            user_threshold_hr: User's threshold heart rate (bpm)
            wallet: User's wallet address
            activity_id: Activity UUID

        Returns:
            SteadyPattern if a valid steady effort is found, None otherwise
        """
        if not tile_samples:
            logger.debug("No tile samples provided")
            return None

        # Determine which data source to use (prefer power over HR)
        has_power = user_ftp and any(s.get("power_w") for s in tile_samples)
        has_hr = user_threshold_hr and any(s.get("hr_bpm") for s in tile_samples)

        if not has_power and not has_hr:
            logger.debug("No power or HR data available for steady detection")
            return None

        # Use power-based detection if available, otherwise fall back to HR
        if has_power:
            return self._detect_from_power(
                tile_samples, user_ftp, wallet, activity_id
            )
        else:
            return self._detect_from_hr(
                tile_samples, user_threshold_hr, wallet, activity_id
            )

    def _detect_from_power(
        self,
        tile_samples: List[dict],
        user_ftp: int,
        wallet: str,
        activity_id: Optional[uuid.UUID],
    ) -> Optional[SteadyPattern]:
        """
        Detect steady pattern from power data.

        Args:
            tile_samples: List of tile samples
            user_ftp: User's FTP in watts
            wallet: User's wallet address
            activity_id: Activity UUID

        Returns:
            Best SteadyPattern or None
        """
        # Filter samples with valid power data
        power_samples = [
            s for s in tile_samples if s.get("power_w") and s["power_w"] > 0
        ]

        if not power_samples:
            return None

        # Calculate intensity zones (fraction of FTP)
        z2_min = user_ftp * self.config.intensity_min
        z3_max = user_ftp * self.config.intensity_max

        # Find candidate windows
        windows = self._find_steady_windows(
            power_samples, z2_min, z3_max, key="power_w"
        )

        if not windows:
            logger.debug("No steady windows found in power data")
            return None

        # Select best window (longest duration, then highest average power)
        best_window = max(
            windows,
            key=lambda w: (w["duration_s"], w["avg_value"]),
        )

        # Calculate normalized power for the window
        window_samples = power_samples[
            best_window["start_idx"] : best_window["end_idx"] + 1
        ]
        np_power = self._calculate_normalized_power(
            [s["power_w"] for s in window_samples]
        )

        # Calculate intensity index (IF = NP / FTP)
        intensity_index = np_power / user_ftp if np_power and user_ftp > 0 else None

        # Calculate variability index (VI = NP / AP)
        variability_index = (
            np_power / best_window["avg_value"]
            if np_power and best_window["avg_value"] > 0
            else None
        )

        # Create pattern
        return SteadyPattern(
            id=uuid.uuid4(),
            activity_id=activity_id or uuid.uuid4(),
            wallet=wallet,
            duration_s=best_window["duration_s"],
            avg_power_w=best_window["avg_value"],
            np_power_w=np_power,
            avg_hr=None,
            intensity_index=intensity_index,
            variability_index=variability_index,
            start_offset_s=best_window["start_t"],
            end_offset_s=best_window["end_t"],
        )

    def _detect_from_hr(
        self,
        tile_samples: List[dict],
        user_threshold_hr: int,
        wallet: str,
        activity_id: Optional[uuid.UUID],
    ) -> Optional[SteadyPattern]:
        """
        Detect steady pattern from heart rate data.

        Args:
            tile_samples: List of tile samples
            user_threshold_hr: User's threshold HR in bpm
            wallet: User's wallet address
            activity_id: Activity UUID

        Returns:
            Best SteadyPattern or None
        """
        # Filter samples with valid HR data
        hr_samples = [s for s in tile_samples if s.get("hr_bpm") and s["hr_bpm"] > 0]

        if not hr_samples:
            return None

        # Calculate HR zones
        z2_min = user_threshold_hr * self.config.hr_z2_min_pct
        z3_max = user_threshold_hr * self.config.hr_z3_max_pct

        # Find candidate windows
        windows = self._find_steady_windows(hr_samples, z2_min, z3_max, key="hr_bpm")

        if not windows:
            logger.debug("No steady windows found in HR data")
            return None

        # Select best window (longest duration)
        best_window = max(windows, key=lambda w: w["duration_s"])

        # Calculate intensity index (IF = avg_hr / threshold_hr)
        intensity_index = (
            best_window["avg_value"] / user_threshold_hr
            if user_threshold_hr > 0
            else None
        )

        # Create pattern (no power metrics available)
        return SteadyPattern(
            id=uuid.uuid4(),
            activity_id=activity_id or uuid.uuid4(),
            wallet=wallet,
            duration_s=best_window["duration_s"],
            avg_power_w=None,
            np_power_w=None,
            avg_hr=int(best_window["avg_value"]),
            intensity_index=intensity_index,
            variability_index=None,  # VI requires power
            start_offset_s=best_window["start_t"],
            end_offset_s=best_window["end_t"],
        )

    def _find_steady_windows(
        self,
        samples: List[dict],
        zone_min: float,
        zone_max: float,
        key: str,
    ) -> List[dict]:
        """
        Find all valid steady windows in the sample data.

        Uses a sliding window approach to find contiguous periods where:
        - Most samples are in the target intensity band
        - Duration meets minimum threshold
        - Variability is below maximum threshold

        Args:
            samples: List of samples with time and intensity data
            zone_min: Lower bound of intensity zone
            zone_max: Upper bound of intensity zone
            key: Key to extract intensity value from samples (e.g., "power_w")

        Returns:
            List of window dicts with keys:
                - start_idx, end_idx: Array indices
                - start_t, end_t: Time offsets in seconds
                - duration_s: Window duration
                - avg_value: Average intensity
                - cv: Coefficient of variation
        """
        if len(samples) < 2:
            return []

        windows = []

        # Try expanding windows starting from each in-band sample
        i = 0
        while i < len(samples):
            value = samples[i].get(key, 0)

            # Skip samples outside the zone
            if not (zone_min <= value <= zone_max):
                i += 1
                continue

            # Start a new window
            window_start = i
            window_end = i

            # Expand window as long as we maintain quality
            while window_end < len(samples) - 1:
                # Try adding next sample
                candidate_end = window_end + 1
                window_samples = samples[window_start : candidate_end + 1]

                # Check duration
                duration = (
                    window_samples[-1]["t"] - window_samples[0]["t"]
                )

                # Extract values for analysis
                values = [s.get(key, 0) for s in window_samples if s.get(key, 0) > 0]

                if not values or len(values) < 2:
                    break

                # Check in-band percentage
                in_band_count = sum(1 for v in values if zone_min <= v <= zone_max)
                in_band_pct = in_band_count / len(values)

                # Check variability
                mean_value = statistics.mean(values)
                if mean_value > 0:
                    std_dev = statistics.stdev(values) if len(values) > 1 else 0
                    cv = std_dev / mean_value
                else:
                    cv = float("inf")

                # If adding this sample would break our criteria, stop expanding
                if (
                    in_band_pct < self.config.in_band_threshold
                    or cv > self.config.variability_max
                ):
                    break

                # Sample passes criteria, include it
                window_end = candidate_end

            # Check if final window meets minimum duration
            window_samples = samples[window_start : window_end + 1]
            duration = window_samples[-1]["t"] - window_samples[0]["t"]

            if duration >= self.config.window_min_s:
                values = [s.get(key, 0) for s in window_samples if s.get(key, 0) > 0]

                if values:
                    mean_value = statistics.mean(values)
                    std_dev = statistics.stdev(values) if len(values) > 1 else 0
                    cv = std_dev / mean_value if mean_value > 0 else 0

                    windows.append(
                        {
                            "start_idx": window_start,
                            "end_idx": window_end,
                            "start_t": window_samples[0]["t"],
                            "end_t": window_samples[-1]["t"],
                            "duration_s": duration,
                            "avg_value": mean_value,
                            "cv": cv,
                        }
                    )

            # Move to next potential window start
            i = window_end + 1

        return windows

    def _calculate_normalized_power(self, power_values: List[float]) -> Optional[float]:
        """
        Calculate Normalized Power (NP) using a rolling average.

        NP = fourth root of (average of (30-second rolling average)^4)

        This metric accounts for the non-linear physiological response to
        varying power output.

        Args:
            power_values: List of power values in watts

        Returns:
            Normalized Power in watts, or None if insufficient data
        """
        if not power_values or len(power_values) < self.config.np_window_s:
            return None

        # Calculate 30-second rolling average
        window_size = min(self.config.np_window_s, len(power_values))
        rolling_avgs = []

        for i in range(len(power_values) - window_size + 1):
            window = power_values[i : i + window_size]
            rolling_avgs.append(statistics.mean(window))

        if not rolling_avgs:
            return None

        # Raise each value to 4th power, average, then take 4th root
        fourth_powers = [p**4 for p in rolling_avgs]
        avg_fourth_power = statistics.mean(fourth_powers)
        normalized_power = avg_fourth_power ** 0.25

        return normalized_power
