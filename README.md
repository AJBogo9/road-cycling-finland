# Road cycling Finland

Scores Finnish state roads in Uusimaa for road cycling from open Väylävirasto data and maps the ones that pass, with the nearest rail or metro station for each.

Map: <https://ajbogo9.github.io/road-cycling-finland/>

## Quick start

```sh
uv sync
uv run roadcycling fetch    # download road layers and stations into data/raw/
uv run roadcycling build    # join and score into data/processed/segments.gpkg
uv run roadcycling export   # write site/data/ for the map
python -m http.server -d site 8765
```

Then open <http://localhost:8765/>. `fetch` caches its downloads; `--refresh` downloads again, and so does a change of the box in `config.toml`. Tests run with `uv run pytest`, and `uv run pytest -m network` adds one test against the live servers.

## What passes

A road segment passes when all four rules hold. A missing value fails its rule.

| Attribute | Rule |
|---|---|
| surface | asphalt or soft asphalt (PAB) |
| speed limit | 80 km/h or less |
| traffic | at most 1000 vehicles a day |
| condition | class 3 or better, on a scale of 1 to 5 |

The map colours passing roads by a score from 0 to 100, the weighted mean of four parts:

| Part | 1 at | 0 at | Weight |
|---|---|---|---|
| traffic, linear in log(vehicles a day) | 200 or fewer | 3000 or more | 0.4 |
| condition | class 5 | class 1 | 0.3 |
| speed limit | 50 km/h or less | 100 km/h or more | 0.2 |
| surface (soft asphalt 0.7) | asphalt | gravel | 0.1 |

The rules and weights are in `config.toml`.

## How the data is joined

Väylävirasto stores each attribute as intervals of road address: road number, road part, and distance along the part. In the road network layer, the M value of each vertex is its road address. The build cuts each road part at every interval end and gives each piece the values that cover it. Where two values cover one piece, such as the two sides of a road or two lanes, the piece keeps the one worse for cycling. The geometry of each piece is cut out of the road by M value.

Rail stations come from Digitraffic and count only if a passenger train departed from them on the day of the fetch. Metro stations come from HSL's GTFS feed. Each road gets the straight-line distance to its nearest station.

## Data

The road layers come from Väylävirasto's WFS at `https://avoinapi.vaylapilvi.fi/vaylatiedot/ows`.

| Data | Source | Licence |
|---|---|---|
| road network | `tiestotiedot:tieosoiteverkko` | CC BY 4.0 |
| speed limits | `tiestotiedot:nopeusrajoitukset` | CC BY 4.0 |
| traffic counts | `tiestotiedot:liikennemaarat` | CC BY 4.0 |
| surface | `tiestotiedot:sidotut_paallysrakenteet`, `tiestotiedot:sitomattomat_pintarakenteet` | CC BY 4.0 |
| pavement condition | `tiestotiedot:paallysteiden_kunto` | CC BY 4.0 |
| rail stations and departures | Fintraffic Digitraffic, `rata.digitraffic.fi` | CC BY 4.0 |
| metro stations | HSL GTFS | CC BY 4.0 |
| basemap | OpenFreeMap, OpenMapTiles, OpenStreetMap contributors | ODbL and the providers' terms |

The code is under the Apache License 2.0.

## First run

Fetched on 2026-10-05 for the default box, 59.75 to 60.95 N and 22.80 to 26.60 E, which holds Uusimaa and parts of the neighbouring regions.

| | |
|---|---|
| segments | 83,379 |
| road length | 9,130 km |
| passing | 2,693 km |
| passing, within 15 km of a station | 1,340 km |
| stations | 78 rail, 30 metro |

## Notebooks

- `notebooks/01-coverage.ipynb`: how much road has each attribute, where values are missing, and one road part rebuilt by hand to check the join.
- `notebooks/02-scoring.ipynb`: distributions, the passing length as each rule moves, and the roads with the most passing length near a station.

Both read `data/processed/segments.gpkg`, so run `fetch` and `build` first.

## Deployment

`.github/workflows/pages.yml` runs `fetch`, `build` and `export` on GitHub Actions and publishes `site/` to GitHub Pages. It runs on every push to `main`, on Wednesdays at 03:00 UTC, and by hand from the Actions tab. The Wednesday run gives the station check a normal weekday timetable.

## Limits

- Only state roads with road numbers below 20000. Väylävirasto publishes traffic counts and pavement condition only for state roads, and road numbers from 20000 up are ramps, service openings, street sections and light traffic paths.
- Pavement condition covers 77% of the road length. In the default box, every segment that passes the other three rules has a condition value.
- Traffic counts date from 2010 to 2025.
- Station distance is a straight line, not a route.
- A station served only on days other than the fetch day drops off the map.
