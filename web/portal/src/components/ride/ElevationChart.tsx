/**
 * ElevationChart - The Command Spine of Ride Navigation
 *
 * Based on dev dashboard's ElevationProfile but enhanced with:
 * - Click-drag rubber-band selection → scopes map view
 * - Climb region shading (like reference design)
 * - Click on climb → elegant map zoom to that climb
 * - Grade-colored elevation line
 */

import { useMemo, useCallback, useRef, useState, useEffect, type CSSProperties } from 'react';
import { useTheme } from '../../contexts/ThemeContext';
import { useFormatters } from '../../hooks/useFormatters';
import { GpsPoint } from '../../lib/api';
import { formatPercent } from '../../lib/formatters';
import { colorWithAlpha, readPortalCanvasPalette } from '../../lib/portalPalette';

interface ElevationChartProps {
  gpsPoints: GpsPoint[];
  height?: number | string;
  onHoverIndex?: (index: number | null) => void;
  hoverIndex?: number | null;
  selectedIndex?: number | null;
  onClickIndex?: (index: number) => void;
  onClearSelection?: () => void;
  onRangeSelect?: (startIndex: number, endIndex: number) => void;
  climbs?: Array<{ startIndex: number; endIndex: number; name?: string }>;
  selectedClimbIndex?: number | null;
  hoveredClimbIndex?: number | null;
  onClimbClick?: (climbIndex: number) => void;
  scopedRange?: { start: number; end: number } | null;  // Persisted scope from parent
  compact?: boolean;
}

// Grade-based coloring (matches dev dashboard)
type GradientTone = 'steep-descent' | 'descent' | 'flat' | 'moderate' | 'steep' | 'extreme';

type PointerGesture = {
  pointerId: number;
  startIndex: number;
  endIndex: number;
};

function distanceBetweenMeters(a: GpsPoint, b: GpsPoint): number {
  const toRad = (value: number) => (value * Math.PI) / 180;
  const earthRadiusM = 6_371_000;
  const dLat = toRad(b.latitude - a.latitude);
  const dLon = toRad(b.longitude - a.longitude);
  const lat1 = toRad(a.latitude);
  const lat2 = toRad(b.latitude);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;

  return 2 * earthRadiusM * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}

function getGradientTone(grade: number): GradientTone {
  if (grade < -5) return 'steep-descent';
  if (grade < 0) return 'descent';
  if (grade < 3) return 'flat';
  if (grade < 6) return 'moderate';
  if (grade < 10) return 'steep';
  return 'extreme';
}

function getGradientColor(
  grade: number,
  palette: ReturnType<typeof readPortalCanvasPalette>,
): string {
  switch (getGradientTone(grade)) {
    case 'steep-descent':
      return palette.route;
    case 'descent':
      return palette.terrain;
    case 'moderate':
      return palette.reward;
    case 'extreme':
      return palette.danger;
    case 'flat':
      return palette.warning;
    case 'steep':
    default:
      return palette.warning;
  }
}

export default function ElevationChart({
  gpsPoints,
  height = '100%',
  onHoverIndex,
  hoverIndex,
  selectedIndex,
  onClickIndex,
  onClearSelection,
  onRangeSelect,
  climbs = [],
  selectedClimbIndex,
  hoveredClimbIndex,
  onClimbClick,
  scopedRange,
  compact = false,
}: ElevationChartProps) {
  const { isDarkMode, themeId } = useTheme();
  const {
    distance: formatDistance,
    distanceValue: formatDistanceValue,
    elevation: formatElevation,
    elevationValue: formatElevationValue,
  } = useFormatters();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });

  // Selection state for rubber-band
  const [isDragging, setIsDragging] = useState(false);
  const [selectionStart, setSelectionStart] = useState<number | null>(null);
  const [selectionEnd, setSelectionEnd] = useState<number | null>(null);
  const [localHoverIndex, setLocalHoverIndex] = useState<number | null>(null);
  const pointerGestureRef = useRef<PointerGesture | null>(null);

  // Chart margins
  const MARGIN = useMemo(
    () => compact
      ? { left: 86, right: 12, top: 8, bottom: 8 }
      : { left: 40, right: 10, top: 8, bottom: 20 },
    [compact],
  );

  const shellStyle = useMemo(() => ({
    '--elevation-chart-height': typeof height === 'number' ? `${height}px` : height,
  }) as CSSProperties, [height]);

  // Process GPS data into elevation/distance/grade arrays
  const { elevations, distances, grades, min, max, totalDistance, totalGain, totalLoss } = useMemo(() => {
    if (gpsPoints.length < 2) {
      return { elevations: [], distances: [], grades: [], min: 0, max: 100, totalDistance: 0, totalGain: 0, totalLoss: 0 };
    }

    const elevations: number[] = [];
    const distances: number[] = [];
    const grades: number[] = [];
    let totalGain = 0;
    let totalLoss = 0;
    let prevElev: number | null = null;

    let cumulativeDistanceM = 0;
    let previousPoint: GpsPoint | null = null;
    const hasProvidedDistance = gpsPoints.some((pt) => typeof pt.distanceM === 'number' && pt.distanceM > 0);

    for (const pt of gpsPoints) {
      const elev = pt.elevationM ?? 0;
      if (hasProvidedDistance) {
        cumulativeDistanceM = pt.distanceM ?? cumulativeDistanceM;
      } else if (previousPoint) {
        cumulativeDistanceM += distanceBetweenMeters(previousPoint, pt);
      }

      const dist = cumulativeDistanceM;
      elevations.push(elev);
      distances.push(dist);

      if (prevElev !== null) {
        const diff = elev - prevElev;
        if (diff > 0) totalGain += diff;
        else totalLoss += Math.abs(diff);
      }
      prevElev = elev;
      previousPoint = pt;
    }

    // Compute grades
    for (let i = 0; i < elevations.length; i++) {
      if (i === 0) {
        grades.push(0);
      } else {
        const dElev = elevations[i] - elevations[i - 1];
        const dDist = distances[i] - distances[i - 1];
        grades.push(dDist > 0 ? (dElev / dDist) * 100 : 0);
      }
    }

    const filtered = elevations.filter((value) => Number.isFinite(value));
    const minE = Math.min(...filtered);
    const maxE = Math.max(...filtered);
    const pad = Math.max((maxE - minE) * 0.1, 10);

    return {
      elevations,
      distances,
      grades,
      min: minE - pad,
      max: maxE + pad,
      totalDistance: distances[distances.length - 1] || 0,
      totalGain: Math.round(totalGain),
      totalLoss: Math.round(totalLoss),
    };
  }, [gpsPoints]);

  // Resize observer - with multiple timing strategies for robust sizing
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const updateSize = () => {
      const rect = container.getBoundingClientRect();
      const parentRect = container.parentElement?.getBoundingClientRect();
      const width = parentRect?.width || rect.width || container.clientWidth;
      const height = parentRect?.height || rect.height || container.clientHeight;

      if (width > 0 && height > 0) {
        setDimensions({ width, height });
      }
    };

    // Multiple timing strategies to catch layout
    const timers = [
      setTimeout(updateSize, 0),
      setTimeout(updateSize, 50),
      setTimeout(updateSize, 150),
      setTimeout(updateSize, 400),
      setTimeout(updateSize, 900),
    ];

    const observer = new ResizeObserver(() => {
      requestAnimationFrame(updateSize);
    });
    observer.observe(container);

    // Also listen for window resize
    window.addEventListener('resize', updateSize);

    return () => {
      timers.forEach(clearTimeout);
      observer.disconnect();
      window.removeEventListener('resize', updateSize);
    };
  }, [elevations.length, height]);

  // Convert index to X pixel position
  const indexToX = useCallback(
    (index: number) => {
      if (elevations.length === 0 || dimensions.width === 0) return MARGIN.left;
      const chartW = dimensions.width - MARGIN.left - MARGIN.right;
      return MARGIN.left + (index / (elevations.length - 1)) * chartW;
    },
    [elevations.length, dimensions.width, MARGIN]
  );

  const getClimbSpanStyle = useCallback(
    (climb: { startIndex: number; endIndex: number }) => {
      const x1 = indexToX(climb.startIndex);
      const x2 = indexToX(climb.endIndex);

      return {
        left: `${Math.min(x1, x2)}px`,
        top: `${MARGIN.top}px`,
        bottom: `${MARGIN.bottom}px`,
        width: `${Math.max(2, Math.abs(x2 - x1))}px`,
      } as CSSProperties;
    },
    [indexToX, MARGIN],
  );

  const selectedClimbOverlay = selectedClimbIndex !== null && selectedClimbIndex !== undefined
    ? climbs[selectedClimbIndex]
    : undefined;
  const hoveredClimbOverlay = hoveredClimbIndex !== null && hoveredClimbIndex !== undefined
    ? climbs[hoveredClimbIndex]
    : undefined;

  // Convert X pixel to index
  const xToIndex = useCallback(
    (x: number) => {
      if (elevations.length === 0 || dimensions.width === 0) return 0;
      const chartW = dimensions.width - MARGIN.left - MARGIN.right;
      const relX = x - MARGIN.left;
      const pct = Math.max(0, Math.min(1, relX / chartW));
      return Math.round(pct * (elevations.length - 1));
    },
    [elevations.length, dimensions.width, MARGIN]
  );

  // Draw chart
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || dimensions.width === 0 || elevations.length < 2) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const monoFontFamily =
      getComputedStyle(document.documentElement).getPropertyValue('--br-font-mono').trim()
      || '"Geist Mono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace';

    const dpr = window.devicePixelRatio || 1;
    canvas.width = dimensions.width * dpr;
    canvas.height = dimensions.height * dpr;
    ctx.scale(dpr, dpr);

    const W = dimensions.width;
    const H = dimensions.height;
    const chartW = W - MARGIN.left - MARGIN.right;
    const chartH = H - MARGIN.top - MARGIN.bottom;
    const elevRange = max - min || 1;
    const palette = readPortalCanvasPalette(containerRef.current ?? canvas);

    // Clear
    ctx.fillStyle = palette.panel;
    ctx.fillRect(0, 0, W, H);

    // Horizontal grid lines
    const gridDivisions = compact ? 2 : 4;
    ctx.strokeStyle = compact ? colorWithAlpha(palette.text, 0.035) : palette.grid;
    ctx.lineWidth = 1;
    for (let i = 0; i <= gridDivisions; i++) {
      const y = MARGIN.top + (chartH / gridDivisions) * i;
      ctx.beginPath();
      ctx.moveTo(MARGIN.left, y);
      ctx.lineTo(W - MARGIN.right, y);
      ctx.stroke();
    }

    // Draw persisted scoped range (blue highlight)
    if (scopedRange) {
      const x1 = indexToX(scopedRange.start);
      const x2 = indexToX(scopedRange.end);
      ctx.fillStyle = colorWithAlpha(palette.selected, compact ? 0.08 : 0.14);
      ctx.fillRect(x1, MARGIN.top, x2 - x1, chartH);
      if (!compact) {
        ctx.strokeStyle = palette.selected;
        ctx.lineWidth = 2;
        ctx.setLineDash([4, 4]);
        ctx.strokeRect(x1, MARGIN.top, x2 - x1, chartH);
        ctx.setLineDash([]);
      }
    }

    const drawClimbBand = (
      climb: { startIndex: number; endIndex: number },
      fill: string,
      stroke: string,
      options: { lineWidth?: number; dash?: number[] } = {},
    ) => {
      const x1 = indexToX(climb.startIndex);
      const x2 = indexToX(climb.endIndex);
      ctx.fillStyle = fill;
      ctx.fillRect(x1, MARGIN.top, x2 - x1, chartH);
      ctx.strokeStyle = stroke;
      ctx.lineWidth = options.lineWidth ?? 1;
      if (options.dash) ctx.setLineDash(options.dash);
      ctx.strokeRect(x1, MARGIN.top, x2 - x1, chartH);
      if (options.dash) ctx.setLineDash([]);
    };

    // Draw climb regions (shaded bands)
    if (compact) {
      if (selectedClimbIndex !== null && selectedClimbIndex !== undefined && climbs[selectedClimbIndex]) {
        drawClimbBand(
          climbs[selectedClimbIndex],
          colorWithAlpha(palette.text, 0.13),
          colorWithAlpha(palette.panel, 0.82),
        );
      }
      if (hoveredClimbIndex !== null && hoveredClimbIndex !== undefined && climbs[hoveredClimbIndex]) {
        drawClimbBand(
          climbs[hoveredClimbIndex],
          colorWithAlpha(palette.selected, 0.17),
          palette.selected,
          { lineWidth: 1.5, dash: [4, 3] },
        );
      }
    } else {
      climbs.forEach((climb, idx) => {
        const isSelected = selectedClimbIndex === idx;
        const isHovered = hoveredClimbIndex === idx;

        // Shaded region
        const fillStyle = isHovered
          ? colorWithAlpha(palette.selected, 0.18)
          : isSelected
          ? colorWithAlpha(palette.success, 0.22)
          : palette.mutedBand;
        const strokeStyle = isHovered ? palette.selected : palette.success;

        drawClimbBand(
          climb,
          fillStyle,
          strokeStyle,
          {
            lineWidth: isHovered || isSelected ? 2 : 0,
            dash: isHovered ? [5, 3] : undefined,
          },
        );

        // Border for selected
        if (!isHovered && !isSelected) return;
      });
    }

    // Draw active drag selection rubber-band (solid border, on top)
    if (selectionStart !== null && selectionEnd !== null) {
      const x1 = indexToX(Math.min(selectionStart, selectionEnd));
      const x2 = indexToX(Math.max(selectionStart, selectionEnd));
      ctx.fillStyle = colorWithAlpha(palette.selected, 0.22);
      ctx.fillRect(x1, MARGIN.top, x2 - x1, chartH);
      ctx.strokeStyle = palette.selected;
      ctx.lineWidth = 2;
      ctx.strokeRect(x1, MARGIN.top, x2 - x1, chartH);
    }

    // Draw filled elevation area
    const segmentWidth = chartW / (elevations.length - 1);

    if (compact) {
      const profileStroke = colorWithAlpha(palette.text, 0.38);
      const profileFill = colorWithAlpha(palette.text, 0.10);
      const baselineY = H - MARGIN.bottom;

      ctx.beginPath();
      ctx.moveTo(MARGIN.left, baselineY);
      elevations.forEach((elevation, index) => {
        const x = MARGIN.left + index * segmentWidth;
        const y = MARGIN.top + chartH - ((elevation - min) / elevRange) * chartH;
        ctx.lineTo(x, y);
      });
      ctx.lineTo(W - MARGIN.right, baselineY);
      ctx.closePath();
      ctx.fillStyle = profileFill;
      ctx.fill();

      ctx.beginPath();
      elevations.forEach((elevation, index) => {
        const x = MARGIN.left + index * segmentWidth;
        const y = MARGIN.top + chartH - ((elevation - min) / elevRange) * chartH;
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = profileStroke;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    } else {
      for (let i = 0; i < elevations.length - 1; i++) {
        const x1 = MARGIN.left + i * segmentWidth;
        const x2 = MARGIN.left + (i + 1) * segmentWidth;
        const y1 = MARGIN.top + chartH - ((elevations[i] - min) / elevRange) * chartH;
        const y2 = MARGIN.top + chartH - ((elevations[i + 1] - min) / elevRange) * chartH;

        const grade = grades[i + 1] || 0;
        const segColor = getGradientColor(grade, palette);

        // Filled segment
        ctx.beginPath();
        ctx.moveTo(x1, H - MARGIN.bottom);
        ctx.lineTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.lineTo(x2, H - MARGIN.bottom);
        ctx.closePath();
        ctx.fillStyle = colorWithAlpha(segColor, 0.25);
        ctx.fill();

        // Line segment
        ctx.strokeStyle = segColor;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
      }
    }

    if (!compact) {
      // Y-axis labels
      ctx.fillStyle = palette.label;
      ctx.font = `12px ${monoFontFamily}`;
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      ctx.fillText(formatElevationValue(max), MARGIN.left - 4, MARGIN.top);
      ctx.fillText(formatElevationValue((max + min) / 2), MARGIN.left - 4, MARGIN.top + chartH / 2);
      ctx.fillText(formatElevationValue(min), MARGIN.left - 4, H - MARGIN.bottom);

      // X-axis distance markers
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      const kmInterval = totalDistance > 100000 ? 20000 : totalDistance > 50000 ? 10000 : 5000;
      for (let m = 0; m < totalDistance; m += kmInterval) {
        const idx = distances.findIndex((d) => d >= m);
        if (idx >= 0) {
          const x = indexToX(idx);
          ctx.fillText(formatDistanceValue(m), x, H - MARGIN.bottom + 4);
        }
      }
      // Always show end distance
      ctx.textAlign = 'right';
      ctx.fillText(formatDistance(totalDistance), W - MARGIN.right, H - MARGIN.bottom + 4);
    }

    // Persisted selected point
    if (selectedIndex !== null && selectedIndex !== undefined && selectedIndex < elevations.length) {
      const x = indexToX(selectedIndex);
      const y = MARGIN.top + chartH - ((elevations[selectedIndex] - min) / elevRange) * chartH;
      const grade = grades[selectedIndex] || 0;

      ctx.strokeStyle = palette.selected;
      ctx.lineWidth = compact ? 1.5 : 2;
      ctx.setLineDash(compact ? [2, 2] : [5, 3]);
      ctx.beginPath();
      ctx.moveTo(x, MARGIN.top);
      ctx.lineTo(x, H - MARGIN.bottom);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.fillStyle = compact ? colorWithAlpha(palette.selected, 0.9) : getGradientColor(grade, palette);
      ctx.beginPath();
      ctx.arc(x, y, compact ? 5 : 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = palette.dotStroke;
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    // Hover crosshair
    const displayIdx = localHoverIndex ?? (hoverIndex !== null ? hoverIndex : null);
    if (displayIdx !== null && displayIdx < elevations.length) {
      const x = indexToX(displayIdx);

      ctx.strokeStyle = palette.hoverLine;
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 2]);
      ctx.beginPath();
      ctx.moveTo(x, MARGIN.top);
      ctx.lineTo(x, H - MARGIN.bottom);
      ctx.stroke();
      ctx.setLineDash([]);

      // Point indicator
      const y = MARGIN.top + chartH - ((elevations[displayIdx] - min) / elevRange) * chartH;
      const grade = grades[displayIdx] || 0;
      ctx.fillStyle = compact ? colorWithAlpha(palette.text, 0.58) : getGradientColor(grade, palette);
      ctx.beginPath();
      ctx.arc(x, y, compact ? 4 : 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = palette.dotStroke;
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    if (!compact) {
      // Corner brackets (tactical framing)
      const bSize = 8;
      ctx.strokeStyle = palette.bracket;
      ctx.lineWidth = 2;
      // Top-left
      ctx.beginPath();
      ctx.moveTo(2, 2 + bSize);
      ctx.lineTo(2, 2);
      ctx.lineTo(2 + bSize, 2);
      ctx.stroke();
      // Top-right
      ctx.beginPath();
      ctx.moveTo(W - 2 - bSize, 2);
      ctx.lineTo(W - 2, 2);
      ctx.lineTo(W - 2, 2 + bSize);
      ctx.stroke();
      // Bottom-left
      ctx.beginPath();
      ctx.moveTo(2, H - 2 - bSize);
      ctx.lineTo(2, H - 2);
      ctx.lineTo(2 + bSize, H - 2);
      ctx.stroke();
      // Bottom-right
      ctx.beginPath();
      ctx.moveTo(W - 2 - bSize, H - 2);
      ctx.lineTo(W - 2, H - 2);
      ctx.lineTo(W - 2, H - 2 - bSize);
      ctx.stroke();
    }
  }, [
    dimensions,
    elevations,
    distances,
    grades,
    min,
    max,
    totalDistance,
    formatDistance,
    formatDistanceValue,
    formatElevationValue,
    isDarkMode,
    themeId,
    localHoverIndex,
    hoverIndex,
    selectedIndex,
    climbs,
    selectedClimbIndex,
    hoveredClimbIndex,
    selectionStart,
    selectionEnd,
    scopedRange,
    indexToX,
    MARGIN,
    compact,
  ]);

  const commitPointSelection = useCallback((index: number) => {
    const clampedIndex = Math.max(0, Math.min(elevations.length - 1, index));
    onClickIndex?.(clampedIndex);
  }, [elevations.length, onClickIndex]);

  // Pointer handlers
  const handlePointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;
      e.preventDefault();
      e.currentTarget.setPointerCapture(e.pointerId);
      const x = e.clientX - rect.left;
      const idx = xToIndex(x);

      pointerGestureRef.current = {
        pointerId: e.pointerId,
        startIndex: idx,
        endIndex: idx,
      };
      setIsDragging(true);
      setSelectionStart(idx);
      setSelectionEnd(idx);
      setLocalHoverIndex(idx);
      onHoverIndex?.(idx);
    },
    [onHoverIndex, xToIndex]
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const x = e.clientX - rect.left;
      const idx = xToIndex(x);

      setLocalHoverIndex(idx);
      onHoverIndex?.(idx);

      const gesture = pointerGestureRef.current;
      if (gesture && gesture.pointerId === e.pointerId) {
        gesture.endIndex = idx;
        setSelectionEnd(idx);
      }
    },
    [xToIndex, onHoverIndex]
  );

  const handlePointerUp = useCallback((e?: React.PointerEvent<HTMLDivElement>) => {
    if (e?.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }

    const gesture = pointerGestureRef.current;
    if (gesture) {
      const start = Math.min(gesture.startIndex, gesture.endIndex);
      const end = Math.max(gesture.startIndex, gesture.endIndex);

      const minimumRangePoints = Math.max(2, Math.min(10, Math.floor(elevations.length * 0.02)));
      if (end - start >= minimumRangePoints && onRangeSelect) {
        onRangeSelect(start, end);
      } else if (onClickIndex) {
        commitPointSelection(gesture.endIndex);
      } else {
        const clickedClimb = climbs.findIndex(
          (c) => gesture.endIndex >= c.startIndex && gesture.endIndex <= c.endIndex
        );
        if (clickedClimb >= 0 && onClimbClick) {
          onClimbClick(clickedClimb);
        }
      }
    }

    pointerGestureRef.current = null;
    setIsDragging(false);
    setSelectionStart(null);
    setSelectionEnd(null);
  }, [
    climbs,
    commitPointSelection,
    elevations.length,
    onClickIndex,
    onClimbClick,
    onRangeSelect,
  ]);

  const handlePointerLeave = useCallback(() => {
    setLocalHoverIndex(null);
    onHoverIndex?.(null);
    if (pointerGestureRef.current) {
      handlePointerUp();
    }
  }, [onHoverIndex, handlePointerUp]);

  const handleKeyDown = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    if (elevations.length < 2) return;

    const baseIndex = selectedIndex ?? hoverIndex ?? 0;
    const step = event.shiftKey ? 10 : 1;
    let nextIndex: number | null = null;

    if (event.key === 'ArrowLeft') nextIndex = baseIndex - step;
    if (event.key === 'ArrowRight') nextIndex = baseIndex + step;
    if (event.key === 'Home') nextIndex = 0;
    if (event.key === 'End') nextIndex = elevations.length - 1;
    if (event.key === 'Escape') {
      event.preventDefault();
      onClearSelection?.();
      onHoverIndex?.(null);
      return;
    }

    if (nextIndex === null) return;
    event.preventDefault();
    const clampedIndex = Math.max(0, Math.min(elevations.length - 1, nextIndex));
    setLocalHoverIndex(clampedIndex);
    onHoverIndex?.(clampedIndex);
    commitPointSelection(clampedIndex);
  }, [
    commitPointSelection,
    elevations.length,
    hoverIndex,
    onClearSelection,
    onHoverIndex,
    selectedIndex,
  ]);

  // Get hover data for display
  const displayIdx = localHoverIndex ?? hoverIndex;
  const hoverElev = displayIdx !== null ? elevations[displayIdx] : null;
  const hoverGrade = displayIdx !== null ? grades[displayIdx] : null;
  const hoverDist = displayIdx !== null ? distances[displayIdx] : null;
  const hoverTone = getGradientTone(hoverGrade || 0);

  if (elevations.length < 2) {
    return (
      <div className="elevation-chart-shell" style={shellStyle}>
        <div className="elevation-chart__empty">
          <span className="elevation-chart__empty-text">No Elevation Data</span>
        </div>
      </div>
    );
  }

  return (
    <div className="elevation-chart-shell" style={shellStyle}>
      {!compact && (
        <div className="elevation-chart__header">
          <span className="elevation-chart__title">Elevation Profile</span>

          <div className="elevation-chart__stats">
            <span className="elevation-chart__stat">↑ {formatElevation(totalGain)} gain</span>
            <span className="elevation-chart__stat">↓ {formatElevation(totalLoss)} loss</span>
            <span className="elevation-chart__stat">↑ {formatElevation(max)} max</span>
            <span className="elevation-chart__stat">↓ {formatElevation(min)} min</span>
          </div>

          {hoverElev !== null && (
            <div className="elevation-chart__hover">
              <span className="elevation-chart__hover-chip">
                {formatDistance(hoverDist || 0)}
              </span>
              <span className={`elevation-chart__hover-chip elevation-chart__hover-chip--grade elevation-chart__hover-chip--${hoverTone}`}>
                {formatElevation(hoverElev)} @ {formatPercent(hoverGrade || 0)}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Canvas container */}
      <div
        ref={containerRef}
        className="elevation-chart__canvas-hitarea"
        role="application"
        tabIndex={0}
        aria-label="Elevation profile. Select a point with click or arrow keys. Drag to select a range."
        onKeyDown={handleKeyDown}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onPointerLeave={handlePointerLeave}
      >
        <canvas
          ref={canvasRef}
          className="elevation-chart__canvas"
        />
        {(selectedClimbOverlay || hoveredClimbOverlay) && (
          <div className="elevation-chart__climb-span-layer" aria-hidden="true">
            {selectedClimbOverlay && (
              <span
                className="elevation-chart__climb-span elevation-chart__climb-span--selected"
                data-climb-index={selectedClimbIndex ?? undefined}
                style={getClimbSpanStyle(selectedClimbOverlay)}
              />
            )}
            {hoveredClimbOverlay && (
              <span
                className="elevation-chart__climb-span elevation-chart__climb-span--hovered"
                data-climb-index={hoveredClimbIndex ?? undefined}
                style={getClimbSpanStyle(hoveredClimbOverlay)}
              />
            )}
          </div>
        )}
      </div>

      {/* Drag hint */}
      {isDragging && (
        <div className="elevation-chart__drag-hint">
          <span>Release to zoom map</span>
        </div>
      )}
    </div>
  );
}
