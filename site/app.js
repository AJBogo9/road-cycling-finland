import * as maplibregl from 'https://unpkg.com/maplibre-gl@6.12.0/dist/maplibre-gl.mjs';

const COLOURS = ['#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b'];
const FAIL = '#a8a7a2';

async function load(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

const [meta, segments, stations] = await Promise.all(
  ['data/meta.json', 'data/segments.geojson', 'data/stations.geojson'].map(load),
);

const $ = (id) => document.getElementById(id);
const slider = $('km');
slider.max = Math.max(40, Math.ceil(meta.max_station_km));
slider.value = meta.max_station_km;
// the ramp runs from the lowest passing score to 100; stops must rise strictly
const floor = Math.min(meta.score_floor, 95);
const RAMP = COLOURS.flatMap((c, i) => [floor + (i * (100 - floor)) / (COLOURS.length - 1), c]);
$('score-floor').textContent = floor;
$('fetched').textContent = meta.fetched;
const f = meta.filters;
$('rule').textContent =
  `Blue roads have asphalt, a speed limit of ${f.max_speed_limit} km/h or less, ` +
  `at most ${f.max_kvl} vehicles a day and condition class ${f.min_condition} or better.`;

const [south, west, north, east] = meta.bbox;
const map = new maplibregl.Map({
  container: 'map',
  style: 'https://tiles.openfreemap.org/styles/positron',
  bounds: [[west, south], [east, north]],
  // keep the box clear of the panel: a side card on desktop, a bottom sheet on phones
  fitBoundsOptions: {
    padding: matchMedia('(max-width: 600px)').matches
      ? { top: 10, right: 10, bottom: Math.round(innerHeight * 0.42), left: 10 }
      : { top: 20, right: 20, bottom: 20, left: 330 },
  },
  attributionControl: { compact: true },
  hash: true,
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');

const near = (km) => ['<=', ['get', 'station_km'], km];
const filters = (km) => ({
  pass: ['all', ['==', ['get', 'passes'], true], near(km)],
  fail: ['all', ['!=', ['get', 'passes'], true], near(km)],
});

function summarise(km) {
  let m = 0;
  for (const s of segments.features) {
    const p = s.properties;
    if (p.passes === true && p.station_km <= km) m += p.length_m;
  }
  $('summary').textContent =
    `${Math.round(m / 1000)} km of carriageway passes all filters within ${km} km of a station.`;
  $('km-out').textContent = km;
}

map.on('load', () => {
  map.addSource('segments', { type: 'geojson', data: segments });
  map.addSource('stations', { type: 'geojson', data: stations });
  const width = ['interpolate', ['linear'], ['zoom'], 8, 1.2, 12, 3, 15, 6];
  const km = Number(slider.value);
  map.addLayer({
    id: 'fail', type: 'line', source: 'segments', filter: filters(km).fail,
    layout: { visibility: 'none', 'line-cap': 'round' },
    paint: { 'line-color': FAIL, 'line-width': width },
  });
  map.addLayer({
    id: 'pass', type: 'line', source: 'segments', filter: filters(km).pass,
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': ['interpolate', ['linear'], ['get', 'score'], ...RAMP], 'line-width': width },
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
  summarise(km);
});

slider.addEventListener('input', () => {
  const km = Number(slider.value);
  const fl = filters(km);
  map.setFilter('pass', fl.pass);
  map.setFilter('fail', fl.fail);
  summarise(km);
});

$('show-fail').addEventListener('change', (e) => {
  map.setLayoutProperty('fail', 'visibility', e.target.checked ? 'visible' : 'none');
});

const known = (v) => v !== null && v !== undefined && v !== '';
const SURFACE = { asphalt: 'asphalt', soft_asphalt: 'soft asphalt (PAB)', gravel: 'gravel' };

function failReasons(p) {
  const out = [];
  if (!known(p.surface)) out.push('surface unknown');
  else if (!f.surfaces.includes(p.surface)) out.push(`${SURFACE[p.surface]} surface`);
  if (!known(p.speed_limit)) out.push('no speed limit');
  else if (p.speed_limit > f.max_speed_limit) out.push(`speed limit over ${f.max_speed_limit}`);
  if (!known(p.kvl)) out.push('no traffic count');
  else if (p.kvl > f.max_kvl) out.push(`over ${f.max_kvl} vehicles/day`);
  if (!known(p.condition)) out.push('no condition data');
  else if (p.condition < f.min_condition) out.push(`condition below ${f.min_condition}`);
  return out;
}

function popupContent(p) {
  const rows = [
    ['Speed limit', known(p.speed_limit) ? `${p.speed_limit} km/h` : 'unknown'],
    ['Traffic', known(p.kvl) ? `${p.kvl} vehicles/day${known(p.kvl_year) ? ` (${p.kvl_year})` : ''}` : 'unknown'],
    ['Surface', SURFACE[p.surface] ?? 'unknown'],
    ['Condition', known(p.condition) ? `class ${p.condition} of 5` : 'unknown'],
    p.passes === true ? ['Score', `${p.score} of 100`] : ['Fails on', failReasons(p).join(', ')],
    ['Station', known(p.station_name) ? `${p.station_name}, ${p.station_km} km` : 'unknown'],
  ];
  const el = document.createElement('div');
  const h = document.createElement('strong');
  h.textContent = `${p.name || 'Unnamed road'} (road ${p.tie}, part ${p.osa})`;
  el.append(h);
  const dl = document.createElement('dl');
  for (const [k, v] of rows) {
    const dt = document.createElement('dt');
    dt.textContent = k;
    const dd = document.createElement('dd');
    dd.textContent = v;
    dl.append(dt, dd);
  }
  el.append(dl);
  return el;
}

const visible = () => ['pass', 'fail'].filter((id) => map.getLayoutProperty(id, 'visibility') !== 'none');

map.on('click', (e) => {
  const pad = 6;
  const box = [[e.point.x - pad, e.point.y - pad], [e.point.x + pad, e.point.y + pad]];
  const [hit] = map.queryRenderedFeatures(box, { layers: visible() });
  if (!hit) return;
  new maplibregl.Popup({ maxWidth: '300px' })
    .setLngLat(e.lngLat)
    .setDOMContent(popupContent(hit.properties))
    .addTo(map);
});
map.on('mousemove', (e) => {
  const hits = map.queryRenderedFeatures(e.point, { layers: visible() });
  map.getCanvas().style.cursor = hits.length ? 'pointer' : '';
});
