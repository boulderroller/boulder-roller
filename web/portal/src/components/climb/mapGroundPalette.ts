/**
 * The map ground — the ledger's one cartographic palette (Tim-ratified
 * 2026-09-05). Every map room draws from this object, so the Climbs index
 * and the climb page are the same city. MapLibre consumes a JSON style, not
 * CSS, so these are literal values rather than custom properties; they are
 * the ledger's warm ramp pushed toward green for landcover and toward slate
 * for water, with no hue brighter than the road hierarchy. The canon route
 * stays cobalt and is the only cobalt on the ground.
 */
export const MAP_GROUND = {
  paper: '#161917',
  land: '#1b201c',
  water: '#141e23',
  waterEdge: '#293b42',
  green: '#252c22',
  building: '#30362f',
  boundary: '#30382f',
  path: '#485046',
  minorRoad: '#62685d',
  majorRoad: '#909383',
  label: '#c4c7bb',

  wood:'#1c261c', grass:'#242b21', farmland:'#21241c', wetland:'#1b2321', sand:'#26241d', ice:'#262929',
  residential:'#1b201c', commercial:'#1e201c', industrial:'#1c1d1a', school:'#20231f', cemetery:'#222820', pitch:'#242b22', quarry:'#221f1b', railway:'#191a18',
  park:'#233022', parkLine:'#33412f',
  contour:'#3a4038', contourIndex:'#4d5449', contourLabel:'#7d857a',
  buildingLine:'#272c27',
  hillShadow:'#030403', hillHighlight:'#4a514a', hillAccent:'#0a0c0a',
  waterLabel:'#6f8792', parkLabel:'#7f9078', peak:'#b5b9ad', unpaved:'#5a6156'
} as const;
