"""download road layers and stations into data/raw/"""

import io
import json
import re
import zipfile
from collections.abc import Callable
from datetime import date
from pathlib import Path

import requests

WFS = "https://avoinapi.vaylapilvi.fi/vaylatiedot/ows"
DIGITRAFFIC = "https://rata.digitraffic.fi/api/v1/metadata/stations"
DIGITRAFFIC_TRAINS = "https://rata.digitraffic.fi/api/v1/trains/"
HSL_GTFS = "https://infopalvelut.storage.hsldev.com/gtfs/hsl.zip"
USER = "road-cycling-finland/0.1"
DIGITRAFFIC_HEADERS = {"Digitraffic-User": USER, "Accept-Encoding": "gzip"}
PASSENGER_TRAINS = {"Long-distance", "Commuter"}
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
    "speed": (
        "tiestotiedot:nopeusrajoitukset",
        [*ADDRESS, "nopeusrajoitus", "sijaintitarkenne_puoli"],
    ),
    "traffic": (
        "tiestotiedot:liikennemaarat",
        [*ADDRESS, "kvl", "laskentavuosi", "laskentatarkkuus"],
    ),
    "pavement": (
        "tiestotiedot:sidotut_paallysrakenteet",
        [*ADDRESS, "tyyppi", "paallysteen_tyyppi"],
    ),
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
    r = session.get(DIGITRAFFIC, headers=DIGITRAFFIC_HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def served_stations(trains) -> list[str]:
    """short codes of stations where a passenger train departs with a commercial stop"""
    codes = {
        row["stationShortCode"]
        for train in trains
        if train["trainCategory"] in PASSENGER_TRAINS
        for row in train["timeTableRows"]
        if row["type"] == "DEPARTURE" and row["trainStopping"] and row.get("commercialStop")
    }
    return sorted(codes)


def fetch_rail_stops(session) -> dict:
    # the passenger flag in the station list also covers stations without trains,
    # so keep only stations with a departure on the fetch day
    day = date.today().isoformat()
    r = session.get(DIGITRAFFIC_TRAINS + day, headers=DIGITRAFFIC_HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return {"date": day, "stations": served_stations(r.json())}


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

    sources: dict[str, tuple[str, Callable[[], object]]] = {
        name: (f"{name}.json", lambda t=type_name, p=props: fetch_layer(session, t, bbox, p))
        for name, (type_name, props) in LAYERS.items()
    }
    sources["rail_stations"] = ("rail_stations.json", lambda: fetch_rail(session))
    sources["rail_stops"] = ("rail_stops.json", lambda: fetch_rail_stops(session))
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
    raw["rail_stops"] = json.loads(read("rail_stops.json"))
    raw["hsl_stops"] = read("hsl_stops.txt")
    raw["fetched"] = json.loads(read("fetched.json"))
    return raw


def load_raw_log(raw_dir) -> dict:
    return json.loads((Path(raw_dir) / "fetched.json").read_text(encoding="utf-8"))
