/**
 * VaultMarkers - Vault locations on the map
 *
 * Renders vault markers with custom styling and popups showing
 * vault name, vertical gain, distance, and completions.
 */

import { useEffect, useRef } from 'react';
import L from 'leaflet';
import { useFormatters } from '../../hooks/useFormatters';
import { Vault } from '../../lib/api';
import { formatDurationWords, formatInteger, formatPercent } from '../../lib/formatters';

interface VaultMarkersProps {
  map: L.Map | null;
  vaults: Vault[];
  visible?: boolean;
}

function createVaultIcon(): L.DivIcon {
  return L.divIcon({
    className: 'vault-marker',
    html: `<div class="vault-marker__pin">
      <svg class="vault-marker__icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M12 2L2 12h3v8h14v-8h3L12 2z"/>
      </svg>
    </div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
    popupAnchor: [0, -16],
  });
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[char] ?? char);
}

export default function VaultMarkers({
  map,
  vaults,
  visible = true,
}: VaultMarkersProps) {
  const { distance: formatDistance, elevation: formatElevation } = useFormatters();
  const layerGroupRef = useRef<L.LayerGroup | null>(null);

  useEffect(() => {
    if (!map) return;

    if (!layerGroupRef.current) {
      layerGroupRef.current = L.layerGroup();
    }

    const layerGroup = layerGroupRef.current;
    layerGroup.clearLayers();

    if (!visible || !vaults.length) {
      layerGroup.remove();
      return;
    }

    const icon = createVaultIcon();

    for (const vault of vaults) {
      const lat = vault.startLat;
      const lon = vault.startLon;
      if (lat == null || lon == null) continue;

      const marker = L.marker([lat, lon], { icon });

      const popupContent = `
        <div class="vault-popup-card">
          <div class="vault-popup-card__title">${escapeHtml(vault.name)}</div>
          <div class="vault-popup-card__metrics">
            <span>${formatElevation(vault.vertM)} vert</span>
            <span>${formatDistance(vault.distanceM)}</span>
          </div>
          <div class="vault-popup-card__metrics vault-popup-card__metrics--muted">
            <span>${formatPercent(vault.avgGradientPct)} avg</span>
            <span>${formatInteger(vault.totalCompletions)} rides</span>
          </div>
          ${vault.komTimeS ? `<div class="vault-popup-card__kom">KOM: ${formatDurationWords(vault.komTimeS)}</div>` : ''}
        </div>
      `;

      marker.bindPopup(popupContent, {
        className: 'vault-popup',
        maxWidth: 250,
      });

      layerGroup.addLayer(marker);
    }

    layerGroup.addTo(map);

    return () => {
      layerGroup.clearLayers();
      layerGroup.remove();
    };
  }, [formatDistance, formatElevation, map, vaults, visible]);

  return null;
}
