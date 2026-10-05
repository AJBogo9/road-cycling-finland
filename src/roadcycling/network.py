"""split road parts at attribute breakpoints and attach attribute values"""

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import LineString, MultiLineString, box

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
# road numbers from 20000 up are ramps, service openings, street sections and light traffic paths
MAX_ROAD_NUMBER = 20000

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
COLUMNS = [
    "tie",
    "osa",
    "ajorata",
    "aet",
    "let",
    "name",
    "speed_limit",
    "kvl",
    "kvl_year",
    "surface",
    "condition",
    "iri",
    "rut_mm",
]


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

    condition = _table(
        raw["condition"], ["tie", "aosa", "aet", "losa", "let", "kunto_lk_nro", "tas", "ura"]
    )
    condition = condition.rename(
        columns={"kunto_lk_nro": "condition", "tas": "iri", "ura": "rut_mm"}
    )

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
        if p["ajorata"] == 2 or p["tie"] >= MAX_ROAD_NUMBER or g is None:
            continue
        lines = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
        arrays = [np.asarray(line, dtype=float) for line in lines]
        if any(a.shape[1] != 4 for a in arrays):
            raise ValueError(f"road {p['tie']}/{p['osa']}: network geometry has no m values")
        parts.append(
            {
                "tie": p["tie"],
                "osa": p["osa"],
                "ajorata": p["ajorata"],
                "name": p.get("nimi"),
                "lines": [a[:, [0, 1, 3]] for a in arrays],
            }
        )
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
        seg = seg.assign(
            tie=part["tie"], osa=part["osa"], ajorata=part["ajorata"], name=part["name"]
        )
        seg["geometry"] = [
            cut_by_m(part["lines"], a, b) for a, b in zip(seg["aet"], seg["let"], strict=True)
        ]
        pieces.append(seg)
    segs = pd.concat(pieces, ignore_index=True)
    segs = segs[segs["geometry"].notna()]
    gdf = gpd.GeoDataFrame(segs[[*COLUMNS, "geometry"]], geometry="geometry", crs=CRS)
    gdf["length_m"] = gdf.length
    return gdf.reset_index(drop=True)


def clip_to_bbox(segments, bbox) -> gpd.GeoDataFrame:
    """keep segments that touch the box; attribute layers were only fetched inside it"""
    south, west, north, east = bbox
    area = gpd.GeoSeries([box(west, south, east, north)], crs="EPSG:4326").to_crs(segments.crs)
    return segments[segments.intersects(area.iloc[0])].reset_index(drop=True)
