/**
 * MapLayerControls - Portal V2 map layer control panel.
 *
 * Keeps layer behavior local while visual chrome lives in portal-spine.css.
 */

import { useState, type ReactNode } from 'react';
import { Check, ChevronDown, Hexagon, Layers, Map, Mountain, Palette, Route, X } from 'lucide-react';
import { TileColorMode, TileColorLegend } from './TileOverlay';
import { GradientLegend } from './GradientClimbOverlay';
import { BASE_MAP_STYLES, BaseMapStyle } from '../../lib/mapColors';
import { formatInteger } from '../../lib/formatters';

interface MapLayerControlsProps {
  showTiles: boolean;
  showTrack: boolean;
  showClimbs: boolean;
  showGradientClimbs: boolean;
  tileColorMode: TileColorMode;
  baseMapStyle: BaseMapStyle;
  onToggleTiles: () => void;
  onToggleTrack: () => void;
  onToggleClimbs: () => void;
  onToggleGradientClimbs: () => void;
  onColorModeChange: (mode: TileColorMode) => void;
  onBaseMapChange: (style: BaseMapStyle) => void;
  tileCount?: number;
  climbCount?: number;
}

interface LayerToggleProps {
  isActive: boolean;
  onClick: () => void;
  icon: ReactNode;
  label: string;
  count?: number;
}

const TILE_COLOR_MODES: TileColorMode[] = ['time', 'gradient', 'power', 'elevation'];
const TILE_COLOR_MODE_LABELS: Record<TileColorMode, string> = {
  time: 'time',
  gradient: 'elev change',
  power: 'power',
  elevation: 'elevation',
};

function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(' ');
}

function LayerToggle({
  isActive,
  onClick,
  icon,
  label,
  count,
}: LayerToggleProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        'map-layer-controls__toggle',
        isActive && 'map-layer-controls__toggle--active',
      )}
      aria-pressed={isActive}
    >
      <span className="map-layer-controls__toggle-main">
        <span className="map-layer-controls__toggle-icon">{icon}</span>
        <span className="map-layer-controls__toggle-label">{label}</span>
        {count !== undefined && count > 0 && (
          <span className="map-layer-controls__pill map-layer-controls__pill--data">{formatInteger(count)}</span>
        )}
      </span>
      <span className="map-layer-controls__checkbox" aria-hidden="true">
        {isActive && <Check size={11} />}
      </span>
    </button>
  );
}

export default function MapLayerControls({
  showTiles,
  showTrack,
  showClimbs,
  showGradientClimbs,
  tileColorMode,
  baseMapStyle,
  onToggleTiles,
  onToggleTrack,
  onToggleClimbs,
  onToggleGradientClimbs,
  onColorModeChange,
  onBaseMapChange,
  tileCount = 0,
  climbCount = 0,
}: MapLayerControlsProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [showColorOptions, setShowColorOptions] = useState(false);
  const [showBaseMapOptions, setShowBaseMapOptions] = useState(false);

  const activeCount = [showTiles, showTrack, showClimbs, showGradientClimbs].filter(Boolean).length;

  if (!isExpanded) {
    return (
      <button
        type="button"
        onClick={() => setIsExpanded(true)}
        className="map-layer-controls__trigger"
        aria-expanded={false}
        aria-label="Open map layer controls"
      >
        <Layers size={14} className="map-layer-controls__trigger-icon" />
        <span className="map-layer-controls__trigger-label">Layers</span>
        {activeCount > 0 && (
          <span className="map-layer-controls__active-count">{formatInteger(activeCount)}</span>
        )}
      </button>
    );
  }

  return (
    <div className="map-layer-controls__panel" role="group" aria-label="Map layer controls">
      <div className="map-layer-controls__header">
        <span className="map-layer-controls__header-main">
          <Layers size={13} className="map-layer-controls__header-icon" />
          <span className="map-layer-controls__title">Map Layers</span>
        </span>
        <button
          type="button"
          onClick={() => setIsExpanded(false)}
          className="map-layer-controls__close"
          aria-label="Close map layer controls"
        >
          <X size={13} />
        </button>
      </div>

      <div className="map-layer-controls__section">
        <button
          type="button"
          onClick={() => setShowBaseMapOptions(!showBaseMapOptions)}
          className="map-layer-controls__section-trigger"
          aria-expanded={showBaseMapOptions}
        >
          <span className="map-layer-controls__section-main">
            <Map size={13} className="map-layer-controls__section-icon" />
            <span className="map-layer-controls__section-title">Base Map</span>
            <span className="map-layer-controls__pill map-layer-controls__pill--label">
              {BASE_MAP_STYLES[baseMapStyle].label}
            </span>
          </span>
          <ChevronDown
            size={13}
            className={cx(
              'map-layer-controls__chevron',
              showBaseMapOptions && 'map-layer-controls__chevron--open',
            )}
          />
        </button>

        {showBaseMapOptions && (
          <div className="map-layer-controls__option-list">
            {(Object.keys(BASE_MAP_STYLES) as BaseMapStyle[]).map((style) => {
              const isActive = baseMapStyle === style;

              return (
                <button
                  key={style}
                  type="button"
                  onClick={() => {
                    onBaseMapChange(style);
                    setShowBaseMapOptions(false);
                  }}
                  className={cx(
                    'map-layer-controls__option',
                    isActive && 'map-layer-controls__option--active',
                  )}
                >
                  <span className="map-layer-controls__option-copy">
                    <span className="map-layer-controls__option-label">
                      {BASE_MAP_STYLES[style].label}
                    </span>
                    <span className="map-layer-controls__option-description">
                      {BASE_MAP_STYLES[style].description}
                    </span>
                  </span>
                  {isActive && <Check size={13} className="map-layer-controls__option-check" />}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="map-layer-controls__toggle-list">
        <LayerToggle
          isActive={showTrack}
          onClick={onToggleTrack}
          icon={<Route size={13} />}
          label="Route"
        />
        <LayerToggle
          isActive={showTiles}
          onClick={onToggleTiles}
          icon={<Hexagon size={13} />}
          label="H3 Tiles"
          count={tileCount}
        />
        <LayerToggle
          isActive={showClimbs}
          onClick={onToggleClimbs}
          icon={<Mountain size={13} />}
          label="Climbs"
          count={climbCount}
        />
        {climbCount > 0 && (
          <LayerToggle
            isActive={showGradientClimbs}
            onClick={onToggleGradientClimbs}
            icon={<Palette size={13} />}
            label="Gradient"
          />
        )}
      </div>

      {showTiles && tileCount > 0 && (
        <div className="map-layer-controls__section">
          <button
            type="button"
            onClick={() => setShowColorOptions(!showColorOptions)}
            className="map-layer-controls__section-trigger"
            aria-expanded={showColorOptions}
          >
            <span className="map-layer-controls__section-title map-layer-controls__section-title--muted">
              Tile Color Mode
            </span>
            <ChevronDown
              size={13}
              className={cx(
                'map-layer-controls__chevron',
                showColorOptions && 'map-layer-controls__chevron--open',
              )}
            />
          </button>

          {showColorOptions && (
            <div className="map-layer-controls__color-panel">
              <div className="map-layer-controls__mode-grid">
                {TILE_COLOR_MODES.map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => onColorModeChange(mode)}
                    className={cx(
                      'map-layer-controls__mode-button',
                      tileColorMode === mode && 'map-layer-controls__mode-button--active',
                    )}
                    aria-pressed={tileColorMode === mode}
                  >
                    {TILE_COLOR_MODE_LABELS[mode]}
                  </button>
                ))}
              </div>
              <div className="map-layer-controls__legend">
                <TileColorLegend mode={tileColorMode} />
              </div>
            </div>
          )}
        </div>
      )}

      {showGradientClimbs && climbCount > 0 && (
        <div className="map-layer-controls__legend-panel">
          <GradientLegend />
        </div>
      )}
    </div>
  );
}
