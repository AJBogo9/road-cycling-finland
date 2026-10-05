import * as maplibregl from 'https://unpkg.com/maplibre-gl@6.12.0/dist/maplibre-gl.mjs';

const COLOURS = ['#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b'];
const SURFACE = { asphalt: 'asphalt', soft_asphalt: 'soft asphalt (PAB)' };

async function load(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

const [meta, roads, stations] = await Promise.all(
  ['data/meta.json', 'data/segments.geojson', 'data/stations.geojson'].map(load),
);

const $ = (id) => document.getElementById(id);
const f = meta.filters;
const km = roads.features.reduce((sum, r) => sum + r.properties.length_m, 0) / 1000;
$('summary').textContent =
  `${Math.round(km).toLocaleString('en')} km of road with asphalt, a speed limit of ` +
  `${f.max_speed_limit} km/h or less, at most ${f.max_kvl} vehicles a day and condition ` +
  `class ${f.min_condition} or better. Circles mark rail and metro stations.`;
$('fetched').textContent = meta.fetched;
// the ramp runs from the lowest score on the map to 100; stops must rise strictly
const floor = Math.min(meta.score_floor, 95);
const ramp = COLOURS.flatMap((c, i) => [floor + (i * (100 - floor)) / (COLOURS.length - 1), c]);
$('score-floor').textContent = floor;

const [south, west, north, east] = meta.bbox;
// keep the box clear of the panel: a side card on desktop, a bottom sheet on phones
const panel = $('panel').getBoundingClientRect();
const map = new maplibregl.Map({
  container: 'map',
  style: 'https://tiles.openfreemap.org/styles/positron',
  bounds: [[west, south], [east, north]],
  fitBoundsOptions: {
    padding: matchMedia('(max-width: 600px)').matches
      ? { top: 10, right: 10, bottom: panel.height + 10, left: 10 }
      : { top: 20, right: 20, bottom: 20, left: panel.right + 20 },
  },
  attributionControl: { compact: true },
  hash: true,
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');

map.on('load', () => {
  map.addSource('roads', { type: 'geojson', data: roads });
  map.addSource('stations', { type: 'geojson', data: stations });
  map.addLayer({
    id: 'roads', type: 'line', source: 'roads',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': ['interpolate', ['linear'], ['get', 'score'], ...ramp],
      'line-width': ['interpolate', ['linear'], ['zoom'], 8, 1.2, 12, 3, 15, 6],
    },
  });
  map.addLayer({
    id: 'stations', type: 'circle', source: 'stations',
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 8, 3, 13, 6],
      'circle-color': '#ffffff', 'circle-stroke-color': '#0b0b0b', 'circle-stroke-width': 1.5,
    },
  });
  map.addLayer({
    id: 'station-labels', type: 'symbol', source: 'stations', minzoom: 9.5,
    layout: {
      'text-field': ['get', 'name'], 'text-font': ['Noto Sans Regular'], 'text-size': 12,
      'text-offset': [0, 0.9], 'text-anchor': 'top',
    },
    paint: { 'text-color': '#0b0b0b', 'text-halo-color': '#ffffff', 'text-halo-width': 1.5 },
  });
});

function popupContent(p) {
  const year = p.kvl_year ? ` (${p.kvl_year})` : '';
  const rows = [
    ['Speed limit', `${p.speed_limit} km/h`],
    ['Traffic', `${p.kvl} vehicles/day${year}`],
    ['Surface', SURFACE[p.surface]],
    ['Condition', `class ${p.condition} of 5`],
    ['Score', `${p.score} of 100`],
    ['Nearest station', `${p.station_name}, ${p.station_km} km`],
  ];
  const el = document.createElement('div');
  const h = document.createElement('strong');
  h.textContent = `${p.name || 'Unnamed road'} (road ${p.tie}, part ${p.osa})`;
  const dl = document.createElement('dl');
  for (const [k, v] of rows) {
    const dt = document.createElement('dt');
    dt.textContent = k;
    const dd = document.createElement('dd');
    dd.textContent = v;
    dl.append(dt, dd);
  }
  el.append(h, dl);
  return el;
}

map.on('click', (e) => {
  // a box around the click, since the lines are thin
  const pad = 6;
  const box = [[e.point.x - pad, e.point.y - pad], [e.point.x + pad, e.point.y + pad]];
  const [hit] = map.queryRenderedFeatures(box, { layers: ['roads'] });
  if (!hit) return;
  new maplibregl.Popup({ maxWidth: '300px' })
    .setLngLat(e.lngLat)
    .setDOMContent(popupContent(hit.properties))
    .addTo(map);
});
map.on('mouseenter', 'roads', () => { map.getCanvas().style.cursor = 'pointer'; });
map.on('mouseleave', 'roads', () => { map.getCanvas().style.cursor = ''; });
