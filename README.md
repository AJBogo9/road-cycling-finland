# Road cycling Finland

Finds quiet state roads with good asphalt in Uusimaa that you can reach by train or metro. Each road segment gets a pass or fail and a score from open Väylävirasto data: speed limit, daily traffic, wearing course and measured pavement condition. A static map shows every passing road coloured by score, with rail and metro stations marked; clicking a road shows its nearest station.

Map: <https://ajbogo9.github.io/road-cycling-finland/>

## Quick start

```sh
uv sync
uv run roadcycling fetch    # download road layers and stations into data/raw/
uv run roadcycling build    # join and score into data/processed/segments.gpkg
uv run roadcycling export   # write site/data/ for the map
python -m http.server -d site 8765
```

Then open <http://localhost:8765/>. `fetch` caches what it downloads; `--refresh` downloads again, and a changed box in `config.toml` triggers a new download by itself.

## What counts as a good road

A segment passes when it has asphalt (normal or soft), a speed limit of at most 80 km/h, at most 1000 vehicles a day and condition class 3 or better on a scale of 1 to 5. A missing value fails, so the map only highlights roads known to be good. The score weighs traffic, condition, speed limit and surface. Every threshold and weight is in `config.toml`.

## First run

Fetched on 2026-10-05 for the default box (59.75 to 60.95 N, 22.80 to 26.60 E), which covers Uusimaa and parts of the neighbouring regions:

| | |
|---|---|
| segments | 83,379 |
| carriageway | 9,130 km |
| passing | 2,693 km |
| passing within 15 km of a station | 1,340 km |
| stations on the map | 78 rail, 30 metro |

## Deployment

`.github/workflows/pages.yml` runs `fetch`, `build` and `export` on GitHub Actions and deploys `site/` to GitHub Pages. It runs on every push to `main`, every Wednesday at 03:00 UTC to refresh the data, and by hand from the Actions tab. The Wednesday run keeps the station check on a normal weekday timetable.

## Notebooks

- `notebooks/01-coverage.ipynb`: how much of the network has each attribute, where values are missing, and a check of the join that rebuilds one road part by hand.
- `notebooks/02-scoring.ipynb`: distributions, how the passing length changes when one threshold moves, and the roads with the most passing length near a station.

Both read `data/processed/segments.gpkg`, so run `fetch` and `build` first.

## Licences

The code is under the Apache License 2.0 (see `LICENSE`). The data comes from these sources under their own licences:

| Data | Source | Licence |
|---|---|---|
| Road network, speed limits, traffic, pavement, condition | Väylävirasto open WFS, `avoinapi.vaylapilvi.fi/vaylatiedot/ows` | CC BY 4.0 |
| Rail stations and departures | Fintraffic Digitraffic, `rata.digitraffic.fi` | CC BY 4.0 |
| Metro stations | HSL GTFS | CC BY 4.0 |
| Basemap | OpenFreeMap, OpenMapTiles, OpenStreetMap contributors | ODbL and the providers' terms |

## Known limits

- Only state roads (maantiet) with road numbers below 20000. Municipal and private roads have none of the four attributes in Väylävirasto's data, and road numbers from 20000 up are ramps, service openings, street sections and light traffic paths.
- Pavement condition is measured on 77% of the road length. In the default box, every segment that passes the other three filters has a condition value.
- Traffic counts are from 2010 to 2025, depending on the road.
- Station distance is a straight line, not a route.
- A rail station counts if a passenger train departed from it on the day of the fetch, so a station served only on other days drops off.

## Layout

```
src/roadcycling/   config, fetch, network (join), score, stations, export, cli
notebooks/         exploration on top of the package
site/              static MapLibre page; site/data/ is generated
docs/superpowers/  design spec and implementation plan
tests/             pytest; `uv run pytest -m network` runs the live end-to-end test
```
