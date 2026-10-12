"""Point Agents/GFAAgent / the Singapore stack's landplot layer at the canonical spine transform `gfa.allowable`.

GFAAgent itself computes *built* GFA per building (footprint area x hasNumberOfFloors -> ontobuiltenv:hasGFA). That is
left as-is. The *allowable* GFA per landplot was computed inline in Deploy/stacks/Singapore/custom_sql_scripts/
landplot_layer.sql (`ref_gfa` = GPR x ST_Area). This module maps Gold `gfa.allowable` rows back to landplot IRIs, so
the stack can read `ref_gfa` from the spine (table `spine_gold.gfa_allowable`, see gfa_allowable.obda).
"""
from __future__ import annotations

import pandas as pd
from cea_agent_bridge import hub_ids_to_iris


def _value_col(gold: pd.DataFrame, key: str, value_col: str | None) -> str:
    if value_col:
        return value_col
    num = [c for c in gold.columns if c != key and pd.api.types.is_float_dtype(gold[c])]
    if len(num) != 1:
        raise ValueError(f"pass value_col; candidate float columns: {num}")
    return num[0]


def gold_to_landplot_ref_gfa(gold: pd.DataFrame, id_bridge: pd.DataFrame, key: str = "plot_id",
                             value_col: str | None = None) -> pd.DataFrame:
    """Gold gfa.allowable -> rows (iri, ref_gfa) for every TWA landplot bridged to a plot hub."""
    col = _value_col(gold, key, value_col)
    iri = hub_ids_to_iris(None, id_bridge, hub="plot")
    br = pd.DataFrame({"plot_id": list(iri), "iri": list(iri.values())})
    out = br.merge(pd.DataFrame(gold)[[key, col]].rename(columns={key: "plot_id", col: "ref_gfa"}), on="plot_id")
    return out[["iri", "plot_id", "ref_gfa"]].sort_values("iri").reset_index(drop=True)


def stack_ref_gfa(plots: pd.DataFrame, zoning: pd.DataFrame) -> pd.Series:
    """What landplot_layer.sql computes today (GPR x area, 0 if GPR not numeric), keyed by plot_id, for comparison.

    The stack uses ST_Area(geom, true) on WGS84 (spheroid); Silver uses planar EPSG:3414 area. They differ by ~1e-4 relative.
    """
    df = pd.DataFrame(plots)[["plot_id", "area_m2"]].merge(zoning[["plot_id", "gross_plot_ratio"]], on="plot_id")
    return (df.area_m2 * df.gross_plot_ratio.fillna(0)).set_axis(df.plot_id)
