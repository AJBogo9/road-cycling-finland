# Road scoring for road cycling: design

Date: 2026-10-05. Status: approved.

## Goal

Find quiet countryside roads in Uusimaa that are good for road cycling and that can be reached by train or metro from Espoo. A good road has asphalt in good condition, a speed limit of at most 80 km/h and little motor traffic.

The repo serves two uses:

1. Exploratory analysis in notebooks, to understand the data and tune what "good" means.
2. A static map website that shows the best roads, which other people can open later.

## Scope of the first slice

In scope:

- State roads (maantiet) inside a configurable bounding box, defaulting to Uusimaa.
- Speed limit, traffic volume, wearing course type and measured pavement condition for each road segment.
- Distance from each segment to the nearest passenger rail station or metro station.
- A score and a pass or fail flag per segment, with thresholds in `config.toml`.
- Two notebooks and a static map page that runs locally.

Out of scope for now, each a later slice:

- Municipal and private roads from OpenStreetMap. Väylävirasto measures none of the four attributes on them.
- Generated ride loops and GPX export.
- Deploying the site. The page has no backend, so Cloudflare Pages can host it from the private repo once the owner decides to publish.

## Data sources

All road layers come from one WFS endpoint, `https://avoinapi.vaylapilvi.fi/vaylatiedot/ows`, queried by bounding box with GeoJSON output.

| Attribute | Layer | Fields used | Unit of location |
|---|---|---|---|
| Base network | `tiestotiedot:tieosoiteverkko` | `tie`, `osa`, `ajorata`, `ajr_pituus`, `nimi`, geometry | one road part per feature |
| Speed limit | `tiestotiedot:nopeusrajoitukset` | `nopeusrajoitus`, `sijaintitarkenne_puoli` | road address interval |
| Traffic volume | `tiestotiedot:liikennemaarat` | `kvl`, `laskentavuosi`, `laskentatarkkuus` | road address interval |
| Wearing course | `tiestotiedot:sidotut_paallysrakenteet` | `paallysteen_tyyppi` where `tyyppi = Kulutuskerros` | road address interval |
| Gravel surface | `tiestotiedot:sitomattomat_pintarakenteet` | presence only | road address interval |
| Pavement condition | `tiestotiedot:paallysteiden_kunto` | `kunto_lk_nro` (1 to 5), `tas`, `ura`, `kaista` | 100 m segment per lane |
| Rail stations | Digitraffic `rata.digitraffic.fi/api/v1/metadata/stations` | `stationName`, `latitude`, `longitude`, `passengerTraffic` | point |
| Metro stations | HSL GTFS `stops.txt` | rows with `vehicle_type = 1` and `location_type = 1` | point |

Road address intervals use `alkusijainti_tie`, `alkusijainti_osa`, `alkusijainti_etaisyys` and the matching `loppusijainti_*` fields. The condition layer uses `tie`, `aosa`, `aet`, `losa`, `let` for the same thing.

Measured on 2026-10-05 for the box 60.00 to 60.45 N, 24.00 to 24.95 E:

- the traffic layer returned 988 intervals, 970 of them with a `kvl` value;
- the condition layer returned 18,095 segments on 163 roads;
- the server returned all 18,095 condition features in one request, with no paging limit.

Digitraffic requires gzip encoding and a `Digitraffic-User` header. The HSL GTFS zip is about 78 MB, and only `stops.txt` is read from it.

## Architecture

```
src/roadcycling/
  config.py     load and validate config.toml
  fetch.py      download layers and stations into data/raw/
  network.py    split road parts at attribute breakpoints, attach attributes
  score.py      filters and 0 to 100 score
  stations.py   station points and nearest-station distance
  export.py     write site/data/segments.geojson, stations.geojson, meta.json
  cli.py        roadcycling fetch | build | export
notebooks/
  01-coverage.ipynb
  02-scoring.ipynb
site/
  index.html, app.js, style.css
tests/
config.toml
```

Data flow: `fetch` writes one GeoPackage per layer to `data/raw/` and skips layers already cached unless `--refresh` is given. `build` reads the raw files and writes `data/processed/segments.gpkg`. `export` writes the files the site reads. `data/` and `site/data/` are gitignored, since anyone can regenerate them.

`fetch` first asks the server for the match count (`resultType=hits`), then compares it with the number of features it received. If the two differ, `fetch` stops with an error, so a truncated download cannot reach the analysis without anyone noticing.

All geometry work happens in EPSG:3067 (ETRS-TM35FIN, metres). The site gets EPSG:4326 with coordinates rounded to five decimals.

Tooling: Python 3.12 with uv, geopandas, shapely, pyogrio, requests, pytest and ruff. The notebooks import the package and hold no logic of their own.

## Network and join

The base network has one line per road part (`tie`, `osa`, `ajorata`). Carriageway 2 of divided roads is dropped, since it repeats carriageway 1 of the same road.

For each road part:

1. Collect every attribute interval that touches the part. An interval that spans several parts is cut at part boundaries, using `ajr_pituus` as the length of each part.
2. Take the union of all interval endpoints as breakpoints, and cut the part into segments between consecutive breakpoints.
3. Give each segment the attribute values whose interval covers it. Where several values cover one segment, keep the one worse for cycling: the highest speed limit of the two road sides, and the lowest condition class among the measured lanes.
4. Cut the geometry with `shapely.ops.substring`, scaling road address distance by the ratio of geometry length to `ajr_pituus`.

The result is a table of homogeneous segments with columns `tie`, `osa`, `aet`, `let`, `name`, `speed_limit`, `kvl`, `kvl_year`, `surface` (`asphalt`, `soft_asphalt`, `gravel` or null), `condition` (1 to 5 or null), `iri`, `rut_mm` and geometry.

`surface` maps the wearing course types as follows: Asfalttibetoni, Kivimastiksiasfaltti and ABK become `asphalt`; PAB-B and PAB-V become `soft_asphalt`; any interval in the gravel layer becomes `gravel`. Where a gravel interval overlaps a wearing course, `gravel` wins, following the worse-value rule in step 3. Any other wearing course type becomes null, and the coverage notebook lists these types by length.

## Scoring

A segment passes when all of these hold, using defaults from `config.toml`:

- `surface` is `asphalt` or `soft_asphalt`;
- `speed_limit` is at most 80;
- `kvl` is at most 1000;
- `condition` is at least 3 (satisfactory).

A missing value fails its filter, so the map only highlights roads known to be good. A `missing` column lists the attributes with no value. Failing segments stay in the data, so the notebooks can study them and the map can draw them in grey.

The score is 100 times the weighted mean of four components, each between 0 and 1:

| Component | 1 at | 0 at | Shape | Default weight |
|---|---|---|---|---|
| traffic | 200 vehicles/day or fewer | 3000 or more | linear in log(kvl) | 0.4 |
| condition | class 5 | class 1 | linear | 0.3 |
| speed limit | 50 km/h or lower | 100 km/h or higher | linear | 0.2 |
| surface | `asphalt` | `gravel` | `soft_asphalt` = 0.7 | 0.1 |

A missing component is left out, and the remaining weights are rescaled to sum to 1. All breakpoints and weights live in `config.toml`.

## Stations

Rail stations are Digitraffic stations in Finland with `passengerTraffic = true`. Metro stations are all 30 HSL metro stations from GTFS. Each segment gets `station_name`, `station_type` (`rail` or `metro`) and `station_km`, the straight-line distance from the segment to the nearest station, computed with `geopandas.sjoin_nearest` in EPSG:3067.

Station distance is an attribute and a map filter, not a pass condition. The map filter default (15 km) is set in `config.toml` and passed to the site through `site/data/meta.json`, together with the date the data was fetched.

## Notebooks

`01-coverage.ipynb` shows, for the configured box, the length of network that has each attribute, the length that passes each filter, and a map of the gaps. It also checks the join by unrolling one road part by hand: it lists its raw intervals, cuts them, and compares the result with `network.py`.

`02-scoring.ipynb` plots the distribution of each attribute and of the score, and shows how the passing length and the top roads change when one threshold moves.

## Site

A static page in `site/` with MapLibre GL JS loaded from a CDN and a basemap that needs no API key. The page has no build step and reads `data/segments.geojson`, `data/stations.geojson` and `data/meta.json`.

- Passing segments are coloured by score. Failing segments are grey and hidden by default, with a toggle to show them.
- A slider sets the maximum station distance.
- Clicking a segment shows its road name and number, speed limit, traffic with count year, surface, condition and nearest station. Condition is shown as the class number, since classes 4 and 5 share the label "hyvä tai erittäin hyvä".
- Stations are drawn as markers labelled by name.
- The layout works at phone width.
- A footer gives the attributions listed below.

Local preview: `python -m http.server -d site`.

## Testing

- `network.py`: a synthetic road part with three overlapping intervals gives the expected segments, values and geometry lengths. An interval that spans two parts is cut correctly. With two sides or lanes, the worse value wins.
- `score.py`: values at and beyond each breakpoint, a missing component, the rescaled weights, and the pass rules with missing values.
- `stations.py`: nearest-station distance on hand-placed points.
- `fetch.py`: a mismatch between the hit count and the received count raises an error. Tested with a stubbed HTTP response.
- One end-to-end test, marked `network` and skipped by default, fetches a small box near Kirkkonummi and builds it.
- Site: screenshots through the chrome-devtools CLI at desktop and phone width, plus a check that the console shows no errors.

## Licences and attribution

- Väylävirasto road data: CC BY 4.0 (licence file in the Digiroad distribution).
- Fintraffic Digitraffic station data: CC BY 4.0.
- HSL GTFS: CC BY 4.0.
- Basemap: OpenStreetMap contributors, plus the tile provider's own attribution.

## Repository

Private GitHub repository `AJBogo9/road-cycling-finland`, default branch `main`, with commits directly to `main`.
