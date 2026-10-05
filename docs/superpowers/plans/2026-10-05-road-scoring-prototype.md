# Road scoring prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Score every state road segment in Uusimaa for road cycling from open Väylävirasto data, and show the good ones near rail and metro stations on a static map.

**Architecture:** A small Python package fetches six WFS layers and two station sources into `data/raw/`, cuts each road network feature into homogeneous segments by road address (using the M values on the network geometry), scores them, attaches the nearest station, and exports GeoJSON for a MapLibre page. Two notebooks sit on top of the package for exploration.

**Tech Stack:** Python 3.12, uv, geopandas 1.2, shapely 2.1, pyogrio, pandas 3, requests, pytest, ruff; MapLibre GL JS 6.12 (ES module from unpkg) with the OpenFreeMap positron style.

**Spec:** `docs/superpowers/specs/2026-10-05-road-scoring-design.md`

## Global Constraints

- All geometry work in EPSG:3067; the site gets EPSG:4326 with five decimals.
- WFS endpoint `https://avoinapi.vaylapilvi.fi/vaylatiedot/ows`, bbox as `south,west,north,east,urn:ogc:def:crs:EPSG::4326`.
- `fetch` compares the `resultType=hits` count with the features received and stops on a mismatch.
- Missing values fail their filter; failing segments stay in the data.
- Pass rule defaults: surface asphalt or soft_asphalt, speed limit at most 80, kvl at most 1000, condition at least 3.
- Score weights: traffic 0.4, condition 0.3, speed limit 0.2, surface 0.1; missing components drop out and the rest are rescaled.
- `data/` and `site/data/` are gitignored.
- Notebooks import the package and hold no logic of their own beyond the hand check.
- Digitraffic requests send a `Digitraffic-User` header.
- Prose: no em or en dashes. Code comments: short lowercase labels.

## Review Focus

1. A box where one layer is empty (no gravel roads, say): build must still run and leave that attribute null. Test in Task 3.
2. Changing `bbox` in `config.toml` after a fetch: the cache describes the old box, so `fetch` must download again. Test in Task 2.
3. Running `build` or `export` before `fetch`: a one-line message telling the user to fetch, not a traceback. Test in Task 6.
4. A network feature whose address range starts above 0 (the single-carriageway feature after a divided section, like road 11269 part 1 from 1088 m): attributes must land at the right address. Tests in Task 3.
5. A segment with missing attributes clicked on the map: the popup shows "unknown", never "null" or "undefined". Checked by screenshot in Task 9.

---

### Task 1: Scaffold and config

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `config.toml`, `src/roadcycling/__init__.py`, `src/roadcycling/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `config.load(path="config.toml") -> Config` with fields `bbox (south, west, north, east)`, `surfaces`, `max_speed_limit`, `max_kvl`, `min_condition`, `traffic`, `condition`, `speed_limit` (each `Ramp(best, worst, weight)`), `surface_weight`, `surface_values: dict[str, float]`, `max_station_km`.

- [ ] **Step 1: Write pyproject, gitignore and config**

`pyproject.toml`:

```toml
[project]
name = "roadcycling"
version = "0.1.0"
description = "Score Finnish state roads for road cycling from open Väylävirasto data"
requires-python = ">=3.12"
dependencies = ["geopandas>=1.1", "shapely>=2.1", "pyogrio>=0.11", "requests>=2.32"]

[project.scripts]
roadcycling = "roadcycling.cli:main"

[dependency-groups]
dev = ["pytest>=8", "ruff>=0.15", "matplotlib>=3.10", "ipykernel>=7", "nbformat>=5.10", "nbconvert>=7.16"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
addopts = "-m 'not network'"
markers = ["network: talks to the live Väylävirasto, Digitraffic and HSL servers"]
testpaths = ["tests"]

[tool.ruff]
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

`.gitignore`:

```
data/
site/data/
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
.ipynb_checkpoints/
```

`config.toml`:

```toml
[area]
# south, west, north, east in degrees; default covers Uusimaa
bbox = [59.75, 22.80, 60.95, 26.60]

[filters]
surfaces = ["asphalt", "soft_asphalt"]
max_speed_limit = 80
max_kvl = 1000
min_condition = 3

[score.traffic]
# vehicles per day, linear in log(kvl)
best = 200
worst = 3000
weight = 0.4

[score.condition]
best = 5
worst = 1
weight = 0.3

[score.speed_limit]
best = 50
worst = 100
weight = 0.2

[score.surface]
weight = 0.1
asphalt = 1.0
soft_asphalt = 0.7
gravel = 0.0

[site]
max_station_km = 15
```

`src/roadcycling/__init__.py`:

```python
"""score Finnish state roads for road cycling"""
```

- [ ] **Step 2: Write the failing test**

`tests/test_config.py`:

```python
from pathlib import Path

import pytest

from roadcycling import config

ROOT = Path(__file__).parents[1]


def test_repo_config_loads():
    cfg = config.load(ROOT / "config.toml")
    assert cfg.bbox == (59.75, 22.80, 60.95, 26.60)
    assert cfg.max_speed_limit == 80
    assert cfg.max_kvl == 1000
    assert cfg.traffic.weight == 0.4
    assert cfg.surface_values == {"asphalt": 1.0, "soft_asphalt": 0.7, "gravel": 0.0}
    assert cfg.max_station_km == 15


def test_swapped_bbox_raises(tmp_path):
    text = (ROOT / "config.toml").read_text(encoding="utf-8")
    text = text.replace("[59.75, 22.80, 60.95, 26.60]", "[60.95, 22.80, 59.75, 26.60]")
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="bbox"):
        config.load(path)
```

- [ ] **Step 3: Run it to see it fail**

Run: `uv sync && uv run pytest tests/test_config.py -v`
Expected: FAIL, `cannot import name 'config'`.

- [ ] **Step 4: Implement**

`src/roadcycling/config.py`:

```python
"""load and validate config.toml"""

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Ramp:
    best: float
    worst: float
    weight: float


@dataclass(frozen=True)
class Config:
    bbox: tuple[float, float, float, float]  # south, west, north, east
    surfaces: tuple[str, ...]
    max_speed_limit: float
    max_kvl: float
    min_condition: float
    traffic: Ramp
    condition: Ramp
    speed_limit: Ramp
    surface_weight: float
    surface_values: dict[str, float]
    max_station_km: float


def load(path: str | Path = "config.toml") -> Config:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    south, west, north, east = raw["area"]["bbox"]
    if not (south < north and west < east):
        raise ValueError(f"bbox must be [south, west, north, east], got {raw['area']['bbox']}")
    filters, score = raw["filters"], raw["score"]
    ramps = {name: Ramp(**score[name]) for name in ("traffic", "condition", "speed_limit")}
    for name, ramp in ramps.items():
        if ramp.best == ramp.worst:
            raise ValueError(f"score.{name}: best and worst must differ")
    surface_values = dict(score["surface"])
    surface_weight = surface_values.pop("weight")
    weights = [r.weight for r in ramps.values()] + [surface_weight]
    if min(weights) < 0 or sum(weights) <= 0:
        raise ValueError(f"weights must be non-negative with a positive sum, got {weights}")
    return Config(
        bbox=(south, west, north, east),
        surfaces=tuple(filters["surfaces"]),
        max_speed_limit=filters["max_speed_limit"],
        max_kvl=filters["max_kvl"],
        min_condition=filters["min_condition"],
        surface_weight=surface_weight,
        surface_values=surface_values,
        max_station_km=raw["site"]["max_station_km"],
        **ramps,
    )
```

- [ ] **Step 5: Run tests and lint**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format --check .`
Expected: 2 passed, no lint errors.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .gitignore config.toml src tests
git commit -m "Add package scaffold and config loader"
```

### Task 2: Fetch

**Files:**
- Create: `src/roadcycling/fetch.py`
- Test: `tests/test_fetch.py`

**Interfaces:**
- Consumes: `Config.bbox`.
- Produces: `fetch.LAYERS` (dict name to `(type_name, properties)`), `fetch.FetchError`, `fetch.wfs_params(type_name, bbox, properties=None, hits=False) -> dict`, `fetch.fetch_layer(session, type_name, bbox, properties=None) -> dict`, `fetch.fetch_all(raw_dir, bbox, refresh=False, session=None) -> list[str]`, `fetch.load_raw(raw_dir) -> dict` with keys `network, speed, traffic, pavement, gravel, condition` (GeoJSON dicts), `rail_stations` (list of dicts), `hsl_stops` (CSV text), `fetched` (`{"bbox": [...], "layers": {name: "YYYY-MM-DD"}}`).

- [ ] **Step 1: Write the failing tests**

`tests/test_fetch.py`:

```python
import io
import zipfile

import pytest

from roadcycling import fetch

BBOX = (60.0, 24.0, 60.5, 25.0)
ALL = [*fetch.LAYERS, "rail_stations", "hsl_stops"]


class FakeResponse:
    def __init__(self, text="", data=None, content=b""):
        self.text, self._data, self.content = text, data, content

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, matched, features):
        self.matched, self.features, self.calls = matched, features, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        if url == fetch.WFS and params.get("resultType") == "hits":
            return FakeResponse(text=f'<wfs:FeatureCollection numberMatched="{self.matched}"/>')
        if url == fetch.WFS:
            return FakeResponse(data={"type": "FeatureCollection", "features": self.features})
        if url == fetch.DIGITRAFFIC:
            return FakeResponse(data=[{"stationName": "Kirkkonummi"}])
        if url == fetch.HSL_GTFS:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("stops.txt", "﻿stop_id,stop_name\n1,A\n")
            return FakeResponse(content=buf.getvalue())
        raise AssertionError(url)


def test_bbox_is_lat_lon_urn():
    params = fetch.wfs_params("t", BBOX, ["a", "b"])
    assert params["bbox"] == "60.0,24.0,60.5,25.0,urn:ogc:def:crs:EPSG::4326"
    assert params["propertyName"] == "a,b"
    assert fetch.wfs_params("t", BBOX, hits=True)["resultType"] == "hits"


def test_count_mismatch_raises():
    with pytest.raises(fetch.FetchError, match="matched 3 features but sent 2"):
        fetch.fetch_layer(FakeSession(3, [{}, {}]), "tiestotiedot:x", BBOX)


def test_fetch_all_writes_then_uses_cache(tmp_path):
    session = FakeSession(1, [{"properties": {}}])
    assert fetch.fetch_all(tmp_path, BBOX, session=session) == ALL
    raw = fetch.load_raw(tmp_path)
    assert raw["hsl_stops"].startswith("stop_id")
    assert raw["fetched"]["bbox"] == list(BBOX)
    calls = len(session.calls)
    assert fetch.fetch_all(tmp_path, BBOX, session=session) == []
    assert len(session.calls) == calls


def test_changed_bbox_fetches_again(tmp_path):
    session = FakeSession(1, [{"properties": {}}])
    fetch.fetch_all(tmp_path, BBOX, session=session)
    assert fetch.fetch_all(tmp_path, (60.1, 24.3, 60.2, 24.5), session=session) == ALL


def test_digitraffic_gets_user_header(tmp_path):
    session = FakeSession(1, [{"properties": {}}])
    fetch.fetch_all(tmp_path, BBOX, session=session)
    headers = next(h for url, _, h in session.calls if url == fetch.DIGITRAFFIC)
    assert headers["Digitraffic-User"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_fetch.py -v`
Expected: FAIL, `cannot import name 'fetch'`.

- [ ] **Step 3: Implement**

`src/roadcycling/fetch.py`:

```python
"""download road layers and stations into data/raw/"""

import io
import json
import re
import zipfile
from datetime import date
from pathlib import Path

import requests

WFS = "https://avoinapi.vaylapilvi.fi/vaylatiedot/ows"
DIGITRAFFIC = "https://rata.digitraffic.fi/api/v1/metadata/stations"
HSL_GTFS = "https://infopalvelut.storage.hsldev.com/gtfs/hsl.zip"
USER = "road-cycling-finland/0.1"
TIMEOUT = 300

ADDRESS = [
    "alkusijainti_tie",
    "alkusijainti_osa",
    "alkusijainti_etaisyys",
    "loppusijainti_tie",
    "loppusijainti_osa",
    "loppusijainti_etaisyys",
]
# name -> (wfs type name, properties to request; None keeps all of them and the geometry)
LAYERS = {
    "network": ("tiestotiedot:tieosoiteverkko", None),
    "speed": ("tiestotiedot:nopeusrajoitukset", [*ADDRESS, "nopeusrajoitus", "sijaintitarkenne_puoli"]),
    "traffic": ("tiestotiedot:liikennemaarat", [*ADDRESS, "kvl", "laskentavuosi", "laskentatarkkuus"]),
    "pavement": ("tiestotiedot:sidotut_paallysrakenteet", [*ADDRESS, "tyyppi", "paallysteen_tyyppi"]),
    "gravel": ("tiestotiedot:sitomattomat_pintarakenteet", ADDRESS),
    "condition": (
        "tiestotiedot:paallysteiden_kunto",
        ["tie", "ajr", "kaista", "aosa", "aet", "losa", "let", "kunto_lk_nro", "tas", "ura"],
    ),
}


class FetchError(RuntimeError):
    pass


def wfs_params(type_name, bbox, properties=None, hits=False) -> dict:
    south, west, north, east = bbox
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": type_name,
        "bbox": f"{south},{west},{north},{east},urn:ogc:def:crs:EPSG::4326",
    }
    if hits:
        params["resultType"] = "hits"
    else:
        params["outputFormat"] = "application/json"
        if properties:
            params["propertyName"] = ",".join(properties)
    return params


def fetch_layer(session, type_name, bbox, properties=None) -> dict:
    r = session.get(WFS, params=wfs_params(type_name, bbox, hits=True), timeout=TIMEOUT)
    r.raise_for_status()
    found = re.search(r'numberMatched="(\d+)"', r.text)
    if not found:
        raise FetchError(f"{type_name}: no numberMatched in the hits response")
    matched = int(found.group(1))
    r = session.get(WFS, params=wfs_params(type_name, bbox, properties), timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if len(data["features"]) != matched:
        raise FetchError(
            f"{type_name}: server matched {matched} features but sent {len(data['features'])}"
        )
    return data


def fetch_rail(session) -> list[dict]:
    headers = {"Digitraffic-User": USER, "Accept-Encoding": "gzip"}
    r = session.get(DIGITRAFFIC, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def fetch_hsl_stops(session) -> str:
    r = session.get(HSL_GTFS, timeout=TIMEOUT)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        return z.read("stops.txt").decode("utf-8-sig")


def _write(path: Path, text: str) -> None:
    # write then rename, so an interrupted download leaves no half file in the cache
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def fetch_all(raw_dir, bbox, refresh=False, session=None) -> list[str]:
    """download every source that is not cached yet; returns the names downloaded"""
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    session = session or requests.Session()
    log_path = raw_dir / "fetched.json"
    log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else {}
    if log.get("bbox") != list(bbox):
        refresh, log = True, {"bbox": list(bbox), "layers": {}}

    sources = {
        name: (f"{name}.json", lambda t=type_name, p=props: fetch_layer(session, t, bbox, p))
        for name, (type_name, props) in LAYERS.items()
    }
    sources["rail_stations"] = ("rail_stations.json", lambda: fetch_rail(session))
    sources["hsl_stops"] = ("hsl_stops.txt", lambda: fetch_hsl_stops(session))

    done = []
    for name, (filename, get) in sources.items():
        path = raw_dir / filename
        if path.exists() and not refresh:
            continue
        data = get()
        _write(path, data if isinstance(data, str) else json.dumps(data, ensure_ascii=False))
        log["layers"][name] = date.today().isoformat()
        _write(log_path, json.dumps(log, indent=2))
        done.append(name)
    return done


def load_raw(raw_dir) -> dict:
    raw_dir = Path(raw_dir)

    def read(name):
        return (raw_dir / name).read_text(encoding="utf-8")

    raw = {name: json.loads(read(f"{name}.json")) for name in LAYERS}
    raw["rail_stations"] = json.loads(read("rail_stations.json"))
    raw["hsl_stops"] = read("hsl_stops.txt")
    raw["fetched"] = json.loads(read("fetched.json"))
    return raw
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_fetch.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/roadcycling/fetch.py tests/test_fetch.py
git commit -m "Fetch road layers and stations with a count check and cache"
```

### Task 3: Network join

**Files:**
- Create: `src/roadcycling/network.py`, `tests/conftest.py`
- Test: `tests/test_network.py`

**Interfaces:**
- Consumes: `load_raw` dict shape from Task 2.
- Produces: `network.CRS = "EPSG:3067"`, `network.surface_class(str | None) -> str | None`, `network.interval_tables(raw) -> dict[str, DataFrame]` (keys `speed, traffic, surface, condition`; columns `tie, aosa, aet, losa, let` plus values), `network.network_parts(geojson) -> list[dict]` (keys `tie, osa, ajorata, name, lines`; `lines` is a list of `(n, 3)` arrays of x, y, m), `network.m_range(lines) -> (float, float)`, `network.cut_by_m(lines, start, end) -> LineString | MultiLineString | None`, `network.on_part(df, osa, m0, m1) -> DataFrame` with `start, end`, `network.split_part(m0, m1, layers) -> DataFrame`, `network.build_segments(raw) -> GeoDataFrame` with columns `tie, osa, ajorata, aet, let, name, speed_limit, kvl, kvl_year, surface, condition, iri, rut_mm, length_m, geometry`.
- `tests/conftest.py` produces the fixture `synthetic_raw` used again in Task 6.

- [ ] **Step 1: Write the fixture and failing tests**

`tests/conftest.py`:

```python
import pytest


def feature(props, geometry=None):
    return {"type": "Feature", "properties": props, "geometry": geometry}


def address(tie, aosa, aet, losa, let):
    return {
        "alkusijainti_tie": tie,
        "alkusijainti_osa": aosa,
        "alkusijainti_etaisyys": aet,
        "loppusijainti_tie": tie,
        "loppusijainti_osa": losa,
        "loppusijainti_etaisyys": let,
    }


def xyzm(points):
    return {"type": "LineString", "coordinates": [[x, y, 0, m] for x, y, m in points]}


@pytest.fixture
def synthetic_raw():
    """one 1 km road part near Kirkkonummi; carriageway 2 must be dropped"""
    x0, y0 = 361000, 6670000
    return {
        "network": {
            "features": [
                feature(
                    {"tie": 1, "osa": 1, "ajorata": 0, "nimi": "Testitie", "ajr_pituus": 1000},
                    xyzm([(x0, y0, 0), (x0 + 1000, y0, 1000)]),
                ),
                feature(
                    {"tie": 1, "osa": 1, "ajorata": 2, "nimi": "Testitie", "ajr_pituus": 1000},
                    xyzm([(x0, y0 + 30, 0), (x0 + 1000, y0 + 30, 1000)]),
                ),
            ]
        },
        "speed": {
            "features": [
                feature({**address(1, 1, 0, 1, 1000), "nopeusrajoitus": "60",
                         "sijaintitarkenne_puoli": "Oikea"})
            ]
        },
        "traffic": {
            "features": [
                feature({**address(1, 1, 0, 1, 1000), "kvl": 400, "laskentavuosi": 2024,
                         "laskentatarkkuus": "8 % virhemarginaali"})
            ]
        },
        "pavement": {
            "features": [
                feature({**address(1, 1, 0, 1, 400), "tyyppi": "Kulutuskerros",
                         "paallysteen_tyyppi": "Pehmeät asfalttibetonit (PAB-B)"}),
                feature({**address(1, 1, 0, 1, 1000), "tyyppi": "Alempi päällystekerros 2",
                         "paallysteen_tyyppi": "Asfalttibetoni"}),
            ]
        },
        "gravel": {"features": []},
        "condition": {
            "features": [
                feature({"tie": 1, "ajr": 0, "kaista": 11, "aosa": 1, "aet": 0, "losa": 1,
                         "let": 1000, "kunto_lk_nro": 4, "tas": 1.5, "ura": 3.0})
            ]
        },
        "rail_stations": [
            {"stationName": "Kirkkonummi", "passengerTraffic": True, "countryCode": "FI",
             "latitude": 60.119648, "longitude": 24.438814}
        ],
        "hsl_stops": "stop_id,stop_name,stop_lat,stop_lon,location_type,vehicle_type\n"
        "1,Kivenlahden metroasema,60.1513,24.6338,1,1\n",
        "fetched": {"bbox": [59.75, 22.8, 60.95, 26.6], "layers": {"network": "2026-10-05"}},
    }
```

`tests/test_network.py`:

```python
import numpy as np
import pandas as pd
import pytest

from roadcycling.network import (
    build_segments,
    cut_by_m,
    on_part,
    split_part,
    surface_class,
)


def line(xs, ms):
    """straight line along the x axis with the given m values"""
    return np.column_stack([xs, np.zeros(len(xs)), ms]).astype(float)


def test_surface_class():
    assert surface_class("Asfalttibetoni") == "asphalt"
    assert surface_class("Kantavan kerroksen asfalttibetoni (ABK)") == "asphalt"
    assert surface_class("Pehmeät asfalttibetonit (PAB-O)") == "soft_asphalt"
    assert surface_class("Ei tietoa") is None
    assert surface_class(None) is None


def test_cut_by_m_interpolates_inside_one_line():
    g = cut_by_m([line([0, 100], [0, 100])], 20, 50)
    assert list(g.coords) == [(20, 0), (50, 0)]


def test_cut_by_m_follows_m_not_position():
    # like road 11269 part 1: the single carriageway starts at address 1088
    g = cut_by_m([line([0, 1000], [1088, 2088])], 1088, 1333)
    assert g.length == pytest.approx(245)
    assert g.coords[0] == (0, 0)


def test_cut_by_m_handles_reversed_lines_and_gaps():
    lines = [line([300, 200], [100, 0]), line([500, 600], [150, 250])]
    g = cut_by_m(lines, 50, 200)
    assert g.geom_type == "MultiLineString"
    assert g.length == pytest.approx(100)
    assert cut_by_m(lines, 110, 140) is None


def test_on_part_cuts_an_interval_spanning_two_parts():
    df = pd.DataFrame({"tie": [1], "aosa": [1], "aet": [800], "losa": [2], "let": [300]})
    assert on_part(df, 1, 0, 1000)[["start", "end"]].values.tolist() == [[800, 1000]]
    assert on_part(df, 2, 0, 700)[["start", "end"]].values.tolist() == [[0, 300]]
    assert on_part(df, 3, 0, 500).empty


def test_on_part_clips_to_an_offset_feature():
    df = pd.DataFrame({"tie": [1], "aosa": [1], "aet": [795], "losa": [1], "let": [1333]})
    assert on_part(df, 1, 1088, 5897)[["start", "end"]].values.tolist() == [[1088, 1333]]


def frame(**columns):
    return pd.DataFrame(columns)


def test_split_part_cuts_at_every_end_and_keeps_the_worse_value():
    layers = {
        "speed": frame(start=[0, 0], end=[600, 1000], speed_limit=[50, 40]),
        "traffic": frame(start=[200], end=[1000], kvl=[300], kvl_year=[2024]),
        "surface": frame(start=[0, 0], end=[1000, 500], surface=["asphalt", "gravel"],
                         surface_rank=[0, 2]),
        "condition": frame(start=[0, 0], end=[500, 500], condition=[4, 2], iri=[1.0, 3.0],
                           rut_mm=[2.0, 6.0]),
    }
    seg = split_part(0, 1000, layers)
    assert seg[["aet", "let"]].values.tolist() == [[0, 200], [200, 500], [500, 600], [600, 1000]]
    assert seg["speed_limit"].tolist() == [50, 50, 50, 40]
    assert np.isnan(seg["kvl"][0]) and seg["kvl"][1:].tolist() == [300, 300, 300]
    assert seg["kvl_year"][1:].tolist() == [2024, 2024, 2024]
    assert seg["surface"].tolist() == ["gravel", "gravel", "asphalt", "asphalt"]
    assert seg["condition"][:2].tolist() == [2, 2] and seg["condition"][2:].isna().all()
    assert seg["iri"][:2].tolist() == [3.0, 3.0]


def test_build_segments_end_to_end(synthetic_raw):
    segs = build_segments(synthetic_raw)
    assert segs.crs == "EPSG:3067"
    assert (segs["ajorata"] == 0).all()
    assert segs[["aet", "let"]].values.tolist() == [[0, 400], [400, 1000]]
    assert segs["surface"].iloc[0] == "soft_asphalt" and pd.isna(segs["surface"].iloc[1])
    assert segs["speed_limit"].tolist() == [60, 60]
    assert segs["kvl"].tolist() == [400, 400]
    assert segs["condition"].tolist() == [4, 4]
    assert segs["name"].tolist() == ["Testitie", "Testitie"]
    assert segs["length_m"].tolist() == pytest.approx([400, 600])


def test_build_segments_with_empty_layers(synthetic_raw):
    synthetic_raw["traffic"] = {"features": []}
    synthetic_raw["pavement"] = {"features": []}
    segs = build_segments(synthetic_raw)
    assert segs[["aet", "let"]].values.tolist() == [[0, 1000]]
    assert segs["kvl"].isna().all() and segs["surface"].isna().all()
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_network.py -v`
Expected: FAIL, `No module named 'roadcycling.network'`.

- [ ] **Step 3: Implement**

`src/roadcycling/network.py`:

```python
"""split road parts at attribute breakpoints and attach attribute values"""

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import LineString, MultiLineString

CRS = "EPSG:3067"

ASPHALT = {
    "Asfalttibetoni",
    "Kivimastiksiasfaltti",
    "Sidekerroksen asfalttibetoni (ABS)",
    "Kantavan kerroksen asfalttibetoni (ABK)",
    "Avoin asfaltti",
}
SOFT_ASPHALT_PREFIX = "Pehmeät asfalttibetonit"
SURFACE_RANK = {"asphalt": 0, "soft_asphalt": 1, "gravel": 2}

# layer -> (column that picks the worst record, True when higher is worse, columns copied)
RULES = {
    "speed": ("speed_limit", True, ["speed_limit"]),
    "traffic": ("kvl", True, ["kvl", "kvl_year"]),
    "surface": ("surface_rank", True, ["surface"]),
    "condition": ("condition", False, ["condition", "iri", "rut_mm"]),
}
ADDRESS = {
    "alkusijainti_tie": "tie",
    "alkusijainti_osa": "aosa",
    "alkusijainti_etaisyys": "aet",
    "loppusijainti_osa": "losa",
    "loppusijainti_etaisyys": "let",
}
COLUMNS = ["tie", "osa", "ajorata", "aet", "let", "name", "speed_limit", "kvl", "kvl_year",
           "surface", "condition", "iri", "rut_mm"]


def surface_class(wearing_course):
    if wearing_course in ASPHALT:
        return "asphalt"
    if isinstance(wearing_course, str) and wearing_course.startswith(SOFT_ASPHALT_PREFIX):
        return "soft_asphalt"
    return None


def _table(geojson, columns) -> pd.DataFrame:
    return pd.DataFrame([f["properties"] for f in geojson["features"]]).reindex(columns=columns)


def _by_address(geojson, columns) -> pd.DataFrame:
    df = _table(geojson, [*ADDRESS, "loppusijainti_tie", *columns])
    # intervals that run onto another road are rare and have no single part numbering
    df = df[df["alkusijainti_tie"] == df["loppusijainti_tie"]]
    return df.rename(columns=ADDRESS)


def interval_tables(raw) -> dict[str, pd.DataFrame]:
    speed = _by_address(raw["speed"], ["nopeusrajoitus"])
    speed["speed_limit"] = pd.to_numeric(speed["nopeusrajoitus"], errors="coerce")

    traffic = _by_address(raw["traffic"], ["kvl", "laskentavuosi"])
    traffic = traffic.rename(columns={"laskentavuosi": "kvl_year"})

    pavement = _by_address(raw["pavement"], ["tyyppi", "paallysteen_tyyppi"])
    pavement = pavement[pavement["tyyppi"] == "Kulutuskerros"]
    pavement["surface"] = pavement["paallysteen_tyyppi"].map(surface_class)
    gravel = _by_address(raw["gravel"], []).assign(surface="gravel")
    surface = pd.concat([pavement, gravel], ignore_index=True)
    surface["surface_rank"] = surface["surface"].map(SURFACE_RANK)

    condition = _table(raw["condition"], ["tie", "aosa", "aet", "losa", "let", "kunto_lk_nro",
                                          "tas", "ura"])
    condition = condition.rename(columns={"kunto_lk_nro": "condition", "tas": "iri",
                                          "ura": "rut_mm"})

    tables = {"speed": speed, "traffic": traffic, "surface": surface, "condition": condition}
    out = {}
    for name, df in tables.items():
        key, _, cols = RULES[name]
        keep = list(dict.fromkeys(["tie", "aosa", "aet", "losa", "let", key, *cols]))
        df = df[keep].dropna(subset=[key])
        for c in ["tie", "aosa", "aet", "losa", "let", key]:
            df[c] = pd.to_numeric(df[c])
        out[name] = df.reset_index(drop=True)
    return out


def network_parts(geojson) -> list[dict]:
    """one entry per network feature, carriageway 2 dropped; lines hold x, y, m"""
    parts = []
    for f in geojson["features"]:
        p, g = f["properties"], f["geometry"]
        if p["ajorata"] == 2 or g is None:
            continue
        lines = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
        arrays = [np.asarray(line, dtype=float) for line in lines]
        if any(a.shape[1] != 4 for a in arrays):
            raise ValueError(f"road {p['tie']}/{p['osa']}: network geometry has no m values")
        parts.append({
            "tie": p["tie"],
            "osa": p["osa"],
            "ajorata": p["ajorata"],
            "name": p.get("nimi"),
            "lines": [a[:, [0, 1, 3]] for a in arrays],
        })
    return parts


def m_range(lines) -> tuple[float, float]:
    ms = np.concatenate([line[:, 2] for line in lines])
    return float(ms.min()), float(ms.max())


def cut_by_m(lines, start, end):
    """the stretch of the lines whose m lies between start and end, or None"""
    pieces = []
    for xym in lines:
        if xym[0, 2] > xym[-1, 2]:
            xym = xym[::-1]
        m = xym[:, 2]
        lo, hi = max(start, m[0]), min(end, m[-1])
        if hi <= lo:
            continue
        inner = xym[(m > lo) & (m < hi), :2]
        first = [np.interp(lo, m, xym[:, 0]), np.interp(lo, m, xym[:, 1])]
        last = [np.interp(hi, m, xym[:, 0]), np.interp(hi, m, xym[:, 1])]
        pieces.append(np.vstack([first, inner, last]))
    if not pieces:
        return None
    return LineString(pieces[0]) if len(pieces) == 1 else MultiLineString(pieces)


def on_part(df, osa, m0, m1) -> pd.DataFrame:
    """intervals covering road part osa, clipped to the feature's address range [m0, m1]"""
    df = df[(df["aosa"] <= osa) & (df["losa"] >= osa)]
    start = np.where(df["aosa"] == osa, df["aet"], -np.inf).clip(m0, m1)
    end = np.where(df["losa"] == osa, df["let"], np.inf).clip(m0, m1)
    df = df.assign(start=start, end=end)
    return df[df["end"] > df["start"]]


def split_part(m0, m1, layers) -> pd.DataFrame:
    """cut [m0, m1] at every interval end; each piece takes the worst covering record per layer"""
    ends = [np.r_[t["start"].to_numpy(), t["end"].to_numpy()] for t in layers.values()]
    cuts = np.unique(np.concatenate([[m0, m1], *ends]))
    seg = pd.DataFrame({"aet": cuts[:-1], "let": cuts[1:]})
    mid = ((cuts[:-1] + cuts[1:]) / 2)[:, None]
    for name, t in layers.items():
        key, higher_is_worse, cols = RULES[name]
        if t.empty:
            for c in cols:
                seg[c] = np.nan
            continue
        cover = (t["start"].to_numpy() <= mid) & (mid < t["end"].to_numpy())
        v = t[key].to_numpy(dtype=float)
        worst = np.where(cover, v if higher_is_worse else -v, -np.inf).argmax(axis=1)
        hit = cover.any(axis=1)
        for c in cols:
            seg[c] = pd.Series(t[c].to_numpy()[worst]).where(hit)
    return seg


def build_segments(raw) -> gpd.GeoDataFrame:
    tables = interval_tables(raw)
    by_tie = {name: dict(list(t.groupby("tie"))) for name, t in tables.items()}
    pieces = []
    for part in network_parts(raw["network"]):
        m0, m1 = m_range(part["lines"])
        layers = {
            name: on_part(by_tie[name].get(part["tie"], tables[name].iloc[:0]), part["osa"], m0, m1)
            for name in tables
        }
        seg = split_part(m0, m1, layers)
        seg = seg.assign(tie=part["tie"], osa=part["osa"], ajorata=part["ajorata"],
                         name=part["name"])
        seg["geometry"] = [cut_by_m(part["lines"], a, b) for a, b in zip(seg["aet"], seg["let"])]
        pieces.append(seg)
    segs = pd.concat(pieces, ignore_index=True)
    segs = segs[segs["geometry"].notna()]
    gdf = gpd.GeoDataFrame(segs[[*COLUMNS, "geometry"]], geometry="geometry", crs=CRS)
    gdf["length_m"] = gdf.length
    return gdf.reset_index(drop=True)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_network.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add src/roadcycling/network.py tests/conftest.py tests/test_network.py
git commit -m "Cut road parts into scored-ready segments by road address"
```

### Task 4: Score

**Files:**
- Create: `src/roadcycling/score.py`
- Test: `tests/test_score.py`

**Interfaces:**
- Consumes: `Config` (Task 1); segment columns `speed_limit, kvl, surface, condition` (Task 3).
- Produces: `score.ramp(x, best, worst) -> ndarray`, `score.components(df, cfg) -> DataFrame` (columns `traffic, condition, speed_limit, surface`), `score.score(df, cfg) -> Series`, `score.passes(df, cfg) -> Series[bool]`, `score.missing(df) -> Series[str]`, `score.apply(df, cfg)` adding `score, passes, missing`.

- [ ] **Step 1: Write the failing tests**

`tests/test_score.py`:

```python
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from roadcycling import config
from roadcycling.score import components, missing, passes, ramp, score

CFG = config.load(Path(__file__).parents[1] / "config.toml")


def rows(**columns):
    n = len(next(iter(columns.values())))
    base = {"speed_limit": [np.nan] * n, "kvl": [np.nan] * n, "surface": [None] * n,
            "condition": [np.nan] * n}
    return pd.DataFrame({**base, **columns})


def test_ramp_ends_middle_and_clipping():
    assert ramp([50, 75, 100, 30, 120], 50, 100).tolist() == [1, 0.5, 0, 1, 0]
    assert ramp([5, 3, 1], 5, 1).tolist() == [1, 0.5, 0]
    assert np.isnan(ramp([np.nan], 50, 100)[0])


def test_traffic_is_linear_in_log_kvl():
    df = rows(kvl=[200, 3000, math.sqrt(200 * 3000), 50, 10000, 0])
    assert components(df, CFG)["traffic"].tolist() == pytest.approx([1, 0, 0.5, 1, 0, 1])


def test_surface_component():
    df = rows(surface=["asphalt", "soft_asphalt", "gravel", None])
    got = components(df, CFG)["surface"].tolist()
    assert got[:3] == [1.0, 0.7, 0.0] and np.isnan(got[3])


def test_missing_component_rescales_the_weights():
    # traffic 1 * 0.4 + condition 0 * 0.3 + speed 1 * 0.2 + surface 1 * 0.1 = 0.7
    full = rows(kvl=[200], condition=[1], speed_limit=[50], surface=["asphalt"])
    assert score(full, CFG).tolist() == pytest.approx([70])
    # without condition: 0.7 / 0.7
    partial = rows(kvl=[200], speed_limit=[50], surface=["asphalt"])
    assert score(partial, CFG).tolist() == pytest.approx([100])
    assert np.isnan(score(rows(kvl=[np.nan]), CFG)[0])


def test_pass_rules_with_limits_and_missing_values():
    df = rows(
        surface=["asphalt", "soft_asphalt", "gravel", None, "asphalt", "asphalt", "asphalt"],
        speed_limit=[80, 60, 60, 60, 90, 60, 60],
        kvl=[1000, 100, 100, 100, 100, 1001, 100],
        condition=[3, 5, 5, 5, 5, 5, np.nan],
    )
    assert passes(df, CFG).tolist() == [True, True, False, False, False, False, False]
    assert missing(df).tolist() == ["", "", "", "surface", "", "", "condition"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_score.py -v`
Expected: FAIL, `No module named 'roadcycling.score'`.

- [ ] **Step 3: Implement**

`src/roadcycling/score.py`:

```python
"""pass filters and a 0 to 100 score per segment"""

import numpy as np
import pandas as pd

CHECKED = ["surface", "speed_limit", "kvl", "condition"]


def ramp(x, best, worst):
    """1 at best, 0 at worst, linear between and clipped outside; nan stays nan"""
    return ((np.asarray(x, dtype=float) - worst) / (best - worst)).clip(0, 1)


def components(df, cfg) -> pd.DataFrame:
    log_kvl = np.log(df["kvl"].astype(float).clip(lower=1))
    t, c, s = cfg.traffic, cfg.condition, cfg.speed_limit
    return pd.DataFrame(
        {
            "traffic": ramp(log_kvl, np.log(t.best), np.log(t.worst)),
            "condition": ramp(df["condition"], c.best, c.worst),
            "speed_limit": ramp(df["speed_limit"], s.best, s.worst),
            "surface": df["surface"].map(cfg.surface_values).astype(float),
        },
        index=df.index,
    )


def score(df, cfg) -> pd.Series:
    c = components(df, cfg)
    w = pd.Series({"traffic": cfg.traffic.weight, "condition": cfg.condition.weight,
                   "speed_limit": cfg.speed_limit.weight, "surface": cfg.surface_weight})
    total = (c.fillna(0) * w).sum(axis=1)
    weight = (c.notna() * w).sum(axis=1)
    return 100 * total / weight.where(weight > 0)


def passes(df, cfg) -> pd.Series:
    return (
        df["surface"].isin(cfg.surfaces)
        & (df["speed_limit"] <= cfg.max_speed_limit)
        & (df["kvl"] <= cfg.max_kvl)
        & (df["condition"] >= cfg.min_condition)
    )


def missing(df) -> pd.Series:
    out = pd.Series("", index=df.index)
    for c in CHECKED:
        out = out + np.where(df[c].isna(), c + ",", "")
    return out.str.rstrip(",")


def apply(df, cfg):
    return df.assign(score=score(df, cfg), passes=passes(df, cfg), missing=missing(df))
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_score.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/roadcycling/score.py tests/test_score.py
git commit -m "Add pass filters and weighted score"
```

### Task 5: Stations

**Files:**
- Create: `src/roadcycling/stations.py`
- Test: `tests/test_stations.py`

**Interfaces:**
- Consumes: `raw["rail_stations"]`, `raw["hsl_stops"]` (Task 2), `network.CRS`.
- Produces: `stations.rail_stations(list) -> GeoDataFrame`, `stations.metro_stations(str) -> GeoDataFrame`, `stations.all_stations(raw) -> GeoDataFrame` (columns `name, type, geometry`, EPSG:3067), `stations.nearest(segments, stations) -> GeoDataFrame` adding `station_name, station_type, station_km`.

- [ ] **Step 1: Write the failing tests**

`tests/test_stations.py`:

```python
import geopandas as gpd
import pytest
from shapely import LineString, Point

from roadcycling.network import CRS
from roadcycling.stations import metro_stations, nearest, rail_stations


def test_rail_keeps_finnish_passenger_stations():
    raw = [
        {"stationName": "A", "passengerTraffic": True, "countryCode": "FI",
         "latitude": 60.1, "longitude": 24.4},
        {"stationName": "B", "passengerTraffic": False, "countryCode": "FI",
         "latitude": 60.2, "longitude": 24.5},
        {"stationName": "C", "passengerTraffic": True, "countryCode": "RU",
         "latitude": 60.3, "longitude": 28.0},
    ]
    got = rail_stations(raw)
    assert got["name"].tolist() == ["A"] and got["type"].tolist() == ["rail"]
    assert got.crs == CRS


def test_metro_reads_station_rows_only():
    text = (
        "stop_id,stop_name,stop_lat,stop_lon,location_type,vehicle_type\n"
        "1,Kivenlahden metroasema,60.15,24.64,1,1\n"
        "2,Kivenlahti,60.15,24.64,0,1\n"
        "3,Espoon asema,60.2,24.65,1,109\n"
    )
    assert metro_stations(text)["name"].tolist() == ["Kivenlahden metroasema"]


def test_nearest_measures_to_the_closest_point_of_the_segment():
    seg = gpd.GeoDataFrame({"name": ["road"]}, geometry=[LineString([(0, 0), (10000, 0)])],
                           crs=CRS)
    st = gpd.GeoDataFrame({"name": ["by the end", "by the middle"], "type": ["rail", "metro"]},
                          geometry=[Point(10000, 2000), Point(5000, 3000)], crs=CRS)
    out = nearest(seg, st)
    assert out["station_name"].tolist() == ["by the end"]
    assert out["station_type"].tolist() == ["rail"]
    assert out["station_km"].tolist() == pytest.approx([2.0])
    assert out["name"].tolist() == ["road"] and len(out) == 1
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_stations.py -v`
Expected: FAIL, `No module named 'roadcycling.stations'`.

- [ ] **Step 3: Implement**

`src/roadcycling/stations.py`:

```python
"""station points and nearest-station distance"""

import csv
import io

import geopandas as gpd
import pandas as pd

from .network import CRS


def _points(names, lons, lats, kind) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"name": names, "type": kind},
        geometry=gpd.points_from_xy(lons, lats),
        crs="EPSG:4326",
    ).to_crs(CRS)


def rail_stations(raw) -> gpd.GeoDataFrame:
    rows = [s for s in raw if s["passengerTraffic"] and s["countryCode"] == "FI"]
    return _points([s["stationName"] for s in rows], [s["longitude"] for s in rows],
                   [s["latitude"] for s in rows], "rail")


def metro_stations(stops_csv) -> gpd.GeoDataFrame:
    rows = [
        r for r in csv.DictReader(io.StringIO(stops_csv))
        if r["vehicle_type"] == "1" and r["location_type"] == "1"
    ]
    return _points([r["stop_name"] for r in rows], [float(r["stop_lon"]) for r in rows],
                   [float(r["stop_lat"]) for r in rows], "metro")


def all_stations(raw) -> gpd.GeoDataFrame:
    parts = [rail_stations(raw["rail_stations"]), metro_stations(raw["hsl_stops"])]
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=CRS)


def nearest(segments, stations) -> gpd.GeoDataFrame:
    s = stations.to_crs(segments.crs).rename(columns={"name": "station_name",
                                                       "type": "station_type"})
    joined = gpd.sjoin_nearest(segments, s[["station_name", "station_type", "geometry"]],
                               how="left", distance_col="station_m")
    joined = joined[~joined.index.duplicated(keep="first")]
    joined["station_km"] = joined.pop("station_m") / 1000
    return joined.drop(columns="index_right")
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_stations.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/roadcycling/stations.py tests/test_stations.py
git commit -m "Add rail and metro stations with nearest-station distance"
```

### Task 6: Export and CLI

**Files:**
- Create: `src/roadcycling/export.py`, `src/roadcycling/cli.py`
- Test: `tests/test_cli.py`, `tests/test_end_to_end.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `export.SITE_COLUMNS`, `export.to_site(segments, stations, cfg, out_dir, fetched_on)` writing `segments.geojson`, `stations.geojson`, `meta.json`; `cli.build(cfg, raw_dir, out) -> GeoDataFrame` writing layers `segments` and `stations` to the GeoPackage; `cli.export_site(cfg, segments_path, raw_dir, site_dir)`; `cli.main(argv=None)`; console script `roadcycling fetch | build | export`.

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:

```python
import json
from pathlib import Path

import pytest

from roadcycling import cli, config

CFG = config.load(Path(__file__).parents[1] / "config.toml")


def write_raw(raw, raw_dir):
    raw_dir.mkdir()
    for name, data in raw.items():
        if name == "hsl_stops":
            (raw_dir / "hsl_stops.txt").write_text(data, encoding="utf-8")
        else:
            (raw_dir / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


def test_build_then_export(synthetic_raw, tmp_path):
    write_raw(synthetic_raw, tmp_path / "raw")
    gpkg = tmp_path / "processed" / "segments.gpkg"
    segs = cli.build(CFG, tmp_path / "raw", gpkg)
    # 0 to 400 is soft asphalt and passes; 400 to 1000 has no wearing course and fails
    assert segs["passes"].tolist() == [True, False]
    cli.export_site(CFG, gpkg, tmp_path / "raw", tmp_path / "site")
    data = json.loads((tmp_path / "site" / "segments.geojson").read_text())
    props = data["features"][0]["properties"]
    assert props["station_name"] == "Kirkkonummi"
    assert props["passes"] is True
    x, y = data["features"][0]["geometry"]["coordinates"][0]
    assert 24 < x < 25 and 60 < y < 61 and round(x, 5) == x
    meta = json.loads((tmp_path / "site" / "meta.json").read_text())
    assert meta["max_station_km"] == 15 and meta["fetched"] == "2026-10-05"
    names = [f["properties"]["name"] for f in
             json.loads((tmp_path / "site" / "stations.geojson").read_text())["features"]]
    assert names == ["Kirkkonummi", "Kivenlahden metroasema"]


def test_build_without_fetch_says_what_to_do(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(
        (Path(__file__).parents[1] / "config.toml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    with pytest.raises(SystemExit, match="roadcycling fetch"):
        cli.main(["build"])
```

`tests/test_end_to_end.py`:

```python
from pathlib import Path

import pytest

from roadcycling import cli, config, fetch

CFG = config.load(Path(__file__).parents[1] / "config.toml")


@pytest.mark.network
def test_kirkkonummi_box(tmp_path):
    fetch.fetch_all(tmp_path / "raw", (60.10, 24.30, 60.20, 24.50))
    segs = cli.build(CFG, tmp_path / "raw", tmp_path / "segments.gpkg")
    assert len(segs) > 100
    assert segs["passes"].any()
    assert segs["station_km"].max() < 20
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL, `cannot import name 'cli'`.

- [ ] **Step 3: Implement**

`src/roadcycling/export.py`:

```python
"""write the files the site reads"""

import json
from pathlib import Path

SITE_COLUMNS = ["tie", "osa", "name", "speed_limit", "kvl", "kvl_year", "surface", "condition",
                "score", "passes", "station_name", "station_type", "station_km", "length_m",
                "geometry"]


def _geojson(gdf, path: Path) -> None:
    path.unlink(missing_ok=True)
    gdf.to_crs(4326).to_file(path, driver="GeoJSON", engine="pyogrio", RFC7946="YES",
                             COORDINATE_PRECISION=5)


def to_site(segments, stations, cfg, out_dir, fetched_on) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    seg = segments[SITE_COLUMNS].copy()
    seg["score"] = seg["score"].round()
    seg["station_km"] = seg["station_km"].round(1)
    seg["length_m"] = seg["length_m"].round()
    _geojson(seg, out / "segments.geojson")

    south, west, north, east = cfg.bbox
    near = stations.to_crs(4326).cx[west:east, south:north]
    _geojson(near[["name", "type", "geometry"]], out / "stations.geojson")

    meta = {
        "fetched": fetched_on,
        "bbox": list(cfg.bbox),
        "max_station_km": cfg.max_station_km,
        "filters": {
            "surfaces": list(cfg.surfaces),
            "max_speed_limit": cfg.max_speed_limit,
            "max_kvl": cfg.max_kvl,
            "min_condition": cfg.min_condition,
        },
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
```

`src/roadcycling/cli.py`:

```python
"""roadcycling fetch | build | export"""

import argparse
from pathlib import Path

import geopandas as gpd

from . import config, export, fetch, network, score, stations

RAW = Path("data/raw")
SEGMENTS = Path("data/processed/segments.gpkg")
SITE_DATA = Path("site/data")


def build(cfg, raw_dir=RAW, out=SEGMENTS) -> gpd.GeoDataFrame:
    raw = fetch.load_raw(raw_dir)
    points = stations.all_stations(raw)
    segs = network.build_segments(raw)
    segs = score.apply(segs, cfg)
    segs = stations.nearest(segs, points)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    segs.to_file(out, layer="segments", driver="GPKG", engine="pyogrio")
    points.to_file(out, layer="stations", driver="GPKG", engine="pyogrio")
    return segs


def export_site(cfg, segments_path=SEGMENTS, raw_dir=RAW, site_dir=SITE_DATA) -> None:
    if not Path(segments_path).exists():
        # pyogrio raises its own error type for a missing file
        raise FileNotFoundError(2, "No such file", str(segments_path))
    segs = gpd.read_file(segments_path, layer="segments")
    points = gpd.read_file(segments_path, layer="stations")
    fetched = fetch.load_raw_log(raw_dir)
    export.to_site(segs, points, cfg, site_dir, min(fetched["layers"].values()))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="roadcycling",
                                     description="Score Finnish state roads for road cycling.")
    parser.add_argument("--config", default="config.toml")
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch", help="download layers and stations into data/raw/")
    f.add_argument("--refresh", action="store_true", help="download again even if cached")
    sub.add_parser("build", help="join and score into data/processed/segments.gpkg")
    sub.add_parser("export", help="write site/data/ for the map")
    args = parser.parse_args(argv)
    cfg = config.load(args.config)
    try:
        if args.command == "fetch":
            done = fetch.fetch_all(RAW, cfg.bbox, refresh=args.refresh)
            print("fetched:", ", ".join(done) if done else "nothing, all cached")
        elif args.command == "build":
            segs = build(cfg)
            km = segs["length_m"].sum() / 1000
            ok = segs.loc[segs["passes"], "length_m"].sum() / 1000
            print(f"{len(segs)} segments, {km:.0f} km, {ok:.0f} km pass, written to {SEGMENTS}")
        elif args.command == "export":
            export_site(cfg)
            print(f"wrote {SITE_DATA}/")
    except FileNotFoundError as e:
        step = "roadcycling build" if args.command == "export" else "roadcycling fetch"
        raise SystemExit(f"missing {e.filename}: run `{step}` first") from None
```

Add to `src/roadcycling/fetch.py`, below `load_raw`:

```python
def load_raw_log(raw_dir) -> dict:
    return json.loads((Path(raw_dir) / "fetched.json").read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest -v`
Expected: all passed, the network test deselected.

- [ ] **Step 5: Run the network test once**

Run: `uv run pytest -m network -v`
Expected: 1 passed (downloads the 78 MB HSL GTFS zip).

- [ ] **Step 6: Commit**

```bash
git add src/roadcycling/export.py src/roadcycling/cli.py src/roadcycling/fetch.py tests/test_cli.py tests/test_end_to_end.py
git commit -m "Add export and the roadcycling command"
```

### Task 7: Real run on Uusimaa

**Files:** none created; produces `data/` and `site/data/`.

- [ ] **Step 1: Fetch, build, export with timing and a memory cap**

```bash
systemd-run --user --scope -p MemoryMax=8G bash -c 'time uv run roadcycling fetch && time uv run roadcycling build && uv run roadcycling export'
du -sh data/raw/* site/data/*
```

Expected: fetch lists all eight sources; build prints segment count, total km and passing km.

- [ ] **Step 2: Check the data assumptions the code makes**

```bash
uv run python - <<'PY'
import numpy as np
from roadcycling import fetch, network
raw = fetch.load_raw("data/raw")
parts = network.network_parts(raw["network"])
bad = [(p["tie"], p["osa"]) for p in parts for l in p["lines"]
       if not (np.all(np.diff(l[:, 2]) >= 0) or np.all(np.diff(l[:, 2]) <= 0))]
print(len(parts), "parts;", len(bad), "lines with m not monotone:", bad[:10])
PY
```

Expected: zero non-monotone lines. If not zero, stop and look at them before going on, since `cut_by_m` assumes monotone m.

- [ ] **Step 3: Note the numbers for the README** (segments, km, passing km, file sizes).

### Task 8: Notebooks

**Files:**
- Create: `notebooks/01-coverage.ipynb`, `notebooks/02-scoring.ipynb` (generated with nbformat from the cells below, then executed in place with `uv run jupyter nbconvert --to notebook --execute --inplace`).

Both notebooks start with:

```python
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd

from roadcycling import config, fetch, network, score

ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
cfg = config.load(ROOT / "config.toml")
segs = gpd.read_file(ROOT / "data/processed/segments.gpkg", layer="segments")
BLUE = "#2a78d6"
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False,
                     "axes.edgecolor": "#52514e", "axes.labelcolor": "#0b0b0b",
                     "xtick.color": "#52514e", "ytick.color": "#52514e"})
```

**01-coverage** cells after the setup:

1. Markdown: what the notebook shows; run `fetch` and `build` first.
2. Coverage table:

```python
def km(mask):
    return segs.loc[mask, "length_m"].sum() / 1000

total = segs["length_m"].sum() / 1000
checks = {
    "speed limit": (segs.speed_limit.notna(), segs.speed_limit <= cfg.max_speed_limit),
    "traffic": (segs.kvl.notna(), segs.kvl <= cfg.max_kvl),
    "surface": (segs.surface.notna(), segs.surface.isin(cfg.surfaces)),
    "condition": (segs.condition.notna(), segs.condition >= cfg.min_condition),
}
table = pd.DataFrame(
    {name: {"km with value": km(has), "% with value": 100 * km(has) / total, "km passing": km(ok)}
     for name, (has, ok) in checks.items()}
).T
complete = segs["missing"].fillna("") == ""
table.loc["all four"] = [km(complete), 100 * km(complete) / total, km(segs.passes)]
print(f"{len(segs)} segments, {total:.0f} km of carriageway")
table.round(0)
```

3. Unmapped wearing courses (single-part intervals only, since their length is a plain difference):

```python
raw = fetch.load_raw(ROOT / "data/raw")
pav = pd.DataFrame([f["properties"] for f in raw["pavement"]["features"]])
pav = pav[(pav.tyyppi == "Kulutuskerros") & (pav.alkusijainti_osa == pav.loppusijainti_osa)]
pav["km"] = (pav.loppusijainti_etaisyys - pav.alkusijainti_etaisyys) / 1000
pav["surface"] = pav.paallysteen_tyyppi.map(network.surface_class)
pav.groupby(["paallysteen_tyyppi", "surface"], dropna=False)["km"].sum().sort_values(ascending=False).round(1)
```

4. Gap map, segments coloured by how many of the four attributes they lack (0 in light grey, 1 to 4 on the validated blue ramp):

```python
from matplotlib.colors import ListedColormap

segs["n_missing"] = segs["missing"].fillna("").map(lambda s: len([x for x in s.split(",") if x]))
cmap = ListedColormap(["#d6d5d0", "#6da7ec", "#3987e5", "#184f95", "#0d366b"])
fig, ax = plt.subplots(figsize=(10, 7))
segs.plot(ax=ax, column="n_missing", categorical=True, cmap=cmap, linewidth=0.7, legend=True,
          legend_kwds={"title": "attributes missing", "frameon": False})
ax.set_axis_off()
```

5. Hand check of road 11269 part 1, carriageway 0 (the feature that starts at address 1088):

```python
TIE, OSA = 11269, 1
tables = network.interval_tables(raw)
part = next(p for p in network.network_parts(raw["network"])
            if (p["tie"], p["osa"], p["ajorata"]) == (TIE, OSA, 0))
m0, m1 = network.m_range(part["lines"])
print("this feature covers addresses", m0, "to", m1)

def touching(name):
    t = tables[name]
    return t[(t.tie == TIE) & (t.aosa <= OSA) & (t.losa >= OSA)]

for name in tables:
    print(name)
    display(touching(name))
```

```python
# cut points by hand: every interval end that falls inside [m0, m1]
cuts = {m0, m1}
for name in tables:
    for _, r in touching(name).iterrows():
        start = r.aet if r.aosa == OSA else m0
        end = r["let"] if r.losa == OSA else m1
        cuts |= {min(max(start, m0), m1), min(max(end, m0), m1)}
cuts = sorted(cuts)

worst = {"speed": ("speed_limit", max), "traffic": ("kvl", max),
         "surface": ("surface_rank", max), "condition": ("condition", min)}
by_hand = pd.DataFrame({"aet": cuts[:-1], "let": cuts[1:]})
for name, (col, pick) in worst.items():
    values = []
    for a, b in zip(cuts, cuts[1:]):
        mid = (a + b) / 2
        cover = [r[col] for _, r in touching(name).iterrows()
                 if (r.aet if r.aosa == OSA else -1e9) <= mid < (r["let"] if r.losa == OSA else 1e9)]
        values.append(pick(cover) if cover else None)
    by_hand[col] = values

built = segs[(segs.tie == TIE) & (segs.osa == OSA) & (segs.ajorata == 0)].sort_values("aet")
built = built.assign(surface_rank=built.surface.map(network.SURFACE_RANK))
cols = ["aet", "let", "speed_limit", "kvl", "surface_rank", "condition"]
side_by_side = by_hand[cols].reset_index(drop=True).compare(built[cols].reset_index(drop=True))
print("differences:", len(side_by_side))
by_hand
```

Expected: `differences: 0`.

**02-scoring** cells after the setup:

1. Markdown: what moves when a threshold moves.
2. Distributions, one small chart per attribute (four panels, one series each, no legend needed):

```python
fig, axes = plt.subplots(2, 2, figsize=(10, 6))
w = segs["length_m"] / 1000
axes[0, 0].hist(segs.speed_limit.dropna(), bins=range(20, 130, 10), weights=w[segs.speed_limit.notna()], color=BLUE)
axes[0, 0].set(title="speed limit (km/h)", ylabel="km")
kvl = segs.kvl.dropna()
axes[0, 1].hist(kvl.clip(lower=10), bins=np.logspace(1, 5, 30), weights=w[kvl.index], color=BLUE)
axes[0, 1].set(xscale="log", title="traffic (vehicles per day)", ylabel="km")
axes[1, 0].hist(segs.condition.dropna(), bins=[0.5, 1.5, 2.5, 3.5, 4.5, 5.5], weights=w[segs.condition.notna()], color=BLUE, rwidth=0.8)
axes[1, 0].set(title="condition class", ylabel="km")
axes[1, 1].hist(segs.score.dropna(), bins=range(0, 105, 5), weights=w[segs.score.notna()], color=BLUE)
axes[1, 1].set(title="score", ylabel="km")
fig.tight_layout()
```

(`import numpy as np` added to the setup cell.)

3. Sensitivity: passing km as each threshold moves, others at their config values:

```python
from dataclasses import replace

def passing_km(**change):
    c = replace(cfg, **change)
    return segs.loc[score.passes(segs, c), "length_m"].sum() / 1000

sweeps = {
    "max_kvl": [250, 500, 750, 1000, 1500, 2000, 3000],
    "max_speed_limit": [50, 60, 70, 80, 90, 100],
    "min_condition": [1, 2, 3, 4, 5],
}
fig, axes = plt.subplots(1, 3, figsize=(12, 3.5), sharey=True)
for ax, (name, values) in zip(axes, sweeps.items()):
    ax.plot(values, [passing_km(**{name: v}) for v in values], color=BLUE, marker="o", markersize=4, linewidth=2)
    ax.axvline(getattr(cfg, name), color="#52514e", linewidth=1, linestyle=":")
    ax.set(xlabel=name, title=name)
axes[0].set_ylabel("passing km")
fig.tight_layout()
```

4. Top roads near a station, and how the list changes with a looser traffic cap:

```python
def top_roads(c, n=15):
    ok = score.passes(segs, c) & (segs.station_km <= c.max_station_km)
    near = segs[ok].assign(weighted=lambda d: d.score * d.length_m)
    g = near.groupby(["tie", "name"], dropna=False).agg(
        m=("length_m", "sum"), weighted=("weighted", "sum"),
        station=("station_name", "first"), station_km=("station_km", "min"))
    g["km"] = g.m / 1000
    g["score"] = g.weighted / g.m
    return g.sort_values("km", ascending=False).head(n)[["km", "score", "station", "station_km"]].round(1)

top_roads(cfg)
```

```python
looser = top_roads(replace(cfg, max_kvl=2000))
looser.assign(new=~looser.index.isin(top_roads(cfg).index))
```

- [ ] **Step 1: Generate both notebooks with nbformat, execute them in place, and check there are no error outputs.**

Run: `uv run jupyter nbconvert --to notebook --execute --inplace notebooks/*.ipynb && grep -c '"output_type": "error"' notebooks/*.ipynb`
Expected: nbconvert succeeds; grep prints 0 for both.

- [ ] **Step 2: Commit**

```bash
git add notebooks
git commit -m "Add coverage and scoring notebooks"
```

### Task 9: Site

**Files:**
- Create: `site/index.html`, `site/app.js`, `site/style.css`

Score colours: the validated blue ramp `#6da7ec, #3987e5, #256abf, #184f95, #0d366b` at scores 45, 59, 72, 86, 100 (lowest passing score is about 46 with the default config). Failing segments `#a8a7a2`.

`site/index.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Road cycling Uusimaa</title>
  <link rel="stylesheet" href="https://unpkg.com/maplibre-gl@6.12.0/dist/maplibre-gl.css">
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div id="map" role="region" aria-label="Map of scored roads"></div>
  <aside id="panel">
    <h1>Quiet roads near a station</h1>
    <p id="summary">Loading the road data.</p>
    <label class="field" for="km">Within <output id="km-out" for="km"></output> km of a rail or metro station</label>
    <input id="km" type="range" min="1" max="40" step="1">
    <label class="check"><input id="show-fail" type="checkbox"> Show roads that fail a filter</label>
    <div class="legend" aria-hidden="true">
      <div class="bar"></div>
      <div class="ticks"><span>45</span><span>score</span><span>100</span></div>
    </div>
    <p class="rule" id="rule"></p>
    <footer>
      Road data © Väylävirasto, CC BY 4.0. Stations © Fintraffic Digitraffic and HSL, CC BY 4.0.
      Data fetched <span id="fetched"></span>.
    </footer>
  </aside>
  <script type="module" src="app.js"></script>
</body>
</html>
```

`site/app.js`:

```js
import * as maplibregl from 'https://unpkg.com/maplibre-gl@6.12.0/dist/maplibre-gl.mjs';

const RAMP = [45, '#6da7ec', 59, '#3987e5', 72, '#256abf', 86, '#184f95', 100, '#0d366b'];
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
slider.value = meta.max_station_km;
$('fetched').textContent = meta.fetched;
const f = meta.filters;
$('rule').textContent =
  `Blue roads have asphalt, a speed limit of ${f.max_speed_limit} km/h or less, ` +
  `under ${f.max_kvl} vehicles a day and condition class ${f.min_condition} or better.`;

const [south, west, north, east] = meta.bbox;
const map = new maplibregl.Map({
  container: 'map',
  style: 'https://tiles.openfreemap.org/styles/positron',
  bounds: [[west, south], [east, north]],
  attributionControl: { compact: true },
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
  $('summary').textContent = `${Math.round(m / 1000)} km of carriageway passes all filters within ${km} km of a station.`;
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

const show = (v, unit = '') => (v === null || v === undefined || v === '' ? 'unknown' : `${v}${unit}`);
const SURFACE = { asphalt: 'asphalt', soft_asphalt: 'soft asphalt (PAB)', gravel: 'gravel' };

function popupContent(p) {
  const rows = [
    ['Speed limit', show(p.speed_limit, ' km/h')],
    ['Traffic', p.kvl == null ? 'unknown' : `${p.kvl} vehicles/day${p.kvl_year ? ` (${p.kvl_year})` : ''}`],
    ['Surface', SURFACE[p.surface] ?? 'unknown'],
    ['Condition', p.condition == null ? 'unknown' : `class ${p.condition} of 5`],
    ['Score', show(p.score)],
    ['Station', p.station_name ? `${p.station_name}, ${p.station_km} km` : 'unknown'],
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

map.on('click', (e) => {
  const pad = 6;
  const box = [[e.point.x - pad, e.point.y - pad], [e.point.x + pad, e.point.y + pad]];
  const layers = ['pass', 'fail'].filter((id) => map.getLayoutProperty(id, 'visibility') !== 'none');
  const [hit] = map.queryRenderedFeatures(box, { layers });
  if (!hit) return;
  new maplibregl.Popup({ maxWidth: '300px' }).setLngLat(e.lngLat).setDOMContent(popupContent(hit.properties)).addTo(map);
});
map.on('mousemove', (e) => {
  const layers = ['pass', 'fail'].filter((id) => map.getLayoutProperty(id, 'visibility') !== 'none');
  map.getCanvas().style.cursor = map.queryRenderedFeatures(e.point, { layers }).length ? 'pointer' : '';
});
```

`site/style.css`:

```css
:root {
  --ink: #0b0b0b;
  --ink-2: #52514e;
  --surface: #fcfcfb;
  --line: #d6d5d0;
}
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; background: #f2f3f0; color: var(--ink);
  font: 14px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; }
#map { position: fixed; inset: 0; }
#panel {
  position: fixed; top: 12px; left: 12px; width: 300px; max-height: calc(100% - 24px);
  overflow: auto; padding: 14px 16px; background: var(--surface);
  border: 1px solid var(--line); border-radius: 8px; box-shadow: 0 2px 10px rgb(0 0 0 / 0.12);
}
h1 { font-size: 17px; margin: 0 0 6px; }
#summary { margin: 0 0 12px; }
.field { display: block; color: var(--ink-2); }
input[type="range"] { width: 100%; margin: 6px 0 10px; accent-color: #256abf; }
.check { display: flex; gap: 6px; align-items: center; color: var(--ink-2); }
.legend { margin: 12px 0 6px; }
.legend .bar { height: 8px; border-radius: 4px;
  background: linear-gradient(to right, #6da7ec, #3987e5, #256abf, #184f95, #0d366b); }
.legend .ticks { display: flex; justify-content: space-between; color: var(--ink-2); font-size: 12px; }
.rule { color: var(--ink-2); font-size: 12px; margin: 6px 0; }
footer { color: var(--ink-2); font-size: 11px; margin-top: 10px; }
.maplibregl-popup-content dl { display: grid; grid-template-columns: auto 1fr; gap: 2px 10px; margin: 6px 0 0; }
.maplibregl-popup-content dt { color: var(--ink-2); }
.maplibregl-popup-content dd { margin: 0; }
@media (max-width: 600px) {
  #panel { top: auto; bottom: 0; left: 0; right: 0; width: auto; max-height: 42%;
    border-radius: 12px 12px 0 0; padding: 12px 16px; }
  h1 { font-size: 16px; }
}
```

- [ ] **Step 1: Serve and screenshot**

```bash
uv run python -m http.server -d site 8765 &   # via run_in_background
chrome-devtools new_page http://localhost:8765/
chrome-devtools take_screenshot --filePath <scratchpad>/desktop.png
chrome-devtools emulate --viewport 390x844x3,mobile,touch
chrome-devtools take_screenshot --filePath <scratchpad>/phone.png
chrome-devtools list_console_messages
```

Expected: blue roads over the basemap, stations with labels at higher zoom, the panel readable at both widths, no console errors.

- [ ] **Step 2: Check the popup on a segment with a missing value** (Review Focus 5): turn on "Show roads that fail a filter", click a grey segment whose `missing` is not empty, screenshot. Expected: "unknown" in the missing rows.

- [ ] **Step 3: Commit**

```bash
git add site
git commit -m "Add static map of scored roads"
```

### Task 10: README, spec sync, GitHub

**Files:**
- Create: `README.md`
- Modify: `docs/superpowers/specs/2026-10-05-road-scoring-design.md` (raw layers stored as the server's GeoJSON, M-based cutting, full surface mapping, GeoPackage layers)

- [ ] **Step 1: Write the README** with: what the repo does, the data sources and licences, quick start (`uv sync`, `uv run roadcycling fetch`, `build`, `export`, `python -m http.server -d site`), the notebooks, the numbers from Task 7, and known limits (state roads only; Digitraffic's passenger flag may include stations without regular service).

- [ ] **Step 2: Run the full check**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format --check .`
Expected: all passed, clean.

- [ ] **Step 3: Commit, create the private repo and push**

```bash
git add README.md docs
git commit -m "Add README and sync the spec with the build"
gh repo create AJBogo9/road-cycling-finland --private --source . --remote origin --push
```
