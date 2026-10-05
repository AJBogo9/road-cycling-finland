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
    w = pd.Series(
        {
            "traffic": cfg.traffic.weight,
            "condition": cfg.condition.weight,
            "speed_limit": cfg.speed_limit.weight,
            "surface": cfg.surface_weight,
        }
    )
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
