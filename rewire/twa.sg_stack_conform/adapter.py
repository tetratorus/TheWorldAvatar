"""twa.sg_stack_conform: TWA Singapore stack snapshot (bronze) -> silver buildings, plots + id_bridge.

Bronze layout (`stack` input, produced by export_stack_snapshot.py from a running Deploy/stacks/Singapore stack):
  landplot.geojson          stack-data-uploader `landplot` subset (EPSG:4326): ogc_fid, LU_DESC, GPR
  buildings.csv             building_iri, footprint_wkt, srid, measured_height   (citydb footprints, sridIn 24500)
  floors.csv                building_iri, storeys                                (ontobuiltenv:hasNumberOfFloors/hasValue)
  usage.csv                 building_iri, usage, usage_share                     (ontobuiltenv:hasPropertyUsage/rdf:type)
  landplot_buildings.csv    ogc_fid, building_uuid                               (BuildingIdentificationAgent output)
Optional `hubs` input: a snapshot of the lake's current Silver plots.parquet / buildings.parquet / id_bridge.parquet.
TWA features that overlap an existing hub (IoU >= min_iou) reuse that hub id (GERS pattern); others get an id minted
from the TWA IRI.

No Silver `zoning`: LAYERS.md gives zoning to ura.mp2019_conform, and the stack's landplot LU_DESC/GPR are copies of
MP2019. Lake.silver_write replaces whole tables, so every output is union-preserving: `plots` and `buildings` keep every
snapshot row (the owner's row wins for plots, TWA's for matched buildings) and only add TWA features that matched no
existing hub; `id_bridge` re-emits every snapshot row whose source is not twa_kg unchanged and replaces only the twa_kg
rows.
"""
from __future__ import annotations

import re
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import wkt

CRS = "EPSG:3414"
KG = "https://www.theworldavatar.com/kg/"
SOURCE = "twa_kg"
# OntoBuiltEnv PropertyUsage subclasses -> spine buildings.use_type.
USE_TYPE = {
    "Domestic": "RESIDENTIAL", "SingleResidential": "RESIDENTIAL", "MultiResidential": "RESIDENTIAL",
    "Office": "OFFICE", "Bank": "OFFICE",
    "RetailEstablishment": "RETAIL", "EatingEstablishment": "RETAIL", "DrinkingEstablishment": "RETAIL",
    "Pharmacy": "RETAIL",
    "IndustrialFacility": "INDUSTRIAL", "Hotel": "HOTEL",
    "School": "SCHOOL", "Education": "SCHOOL", "University": "SCHOOL",
    "Hospital": "HOSPITAL", "Clinic": "HOSPITAL", "Medical": "HOSPITAL",
}


PLOT_COLS = ["plot_id", "area_m2", "source_version", "geometry"]
BRIDGE_COLS = ["source", "source_id", "hub", "hub_id", "match_method", "confidence", "source_version"]
BUILDING_COLS = ["building_id", "plot_id", "district_id", "height_m", "storeys", "use_type", "year_built",
                 "source_version", "geometry"]


def _csv(d: Path, name: str) -> pd.DataFrame | None:
    p = d / name
    return pd.read_csv(p, dtype=str) if p.exists() else None


def _local(iri: str) -> str:
    return re.split(r"[/#]", str(iri).rstrip("/"))[-1]


def _reconcile(src: gpd.GeoDataFrame, minted: pd.Series, hubs: gpd.GeoDataFrame | None, key: str,
               min_iou: float) -> pd.DataFrame:
    """hub_id, match_method, confidence per source row: best-IoU existing hub, else the minted id."""
    out = pd.DataFrame({"hub_id": minted.values, "match_method": "exact", "confidence": 1.0}, index=src.index)
    if hubs is None or hubs.empty:
        return out
    hubs = hubs.to_crs(CRS)[[key, "geometry"]]
    pairs = gpd.sjoin(src[["geometry"]], hubs, predicate="intersects", how="inner")
    for idx, row in pairs.iterrows():
        a, b = src.geometry.loc[idx], hubs.geometry.loc[row["index_right"]]
        iou = a.intersection(b).area / a.union(b).area
        if iou >= min_iou and (out.at[idx, "match_method"] == "exact" or iou > out.at[idx, "confidence"]):
            out.loc[idx] = [row[key], "spatial_overlap", round(float(iou), 6)]
    return out


def _bridge(source_ids: pd.Series, hub: str, rec: pd.DataFrame, version: str) -> pd.DataFrame:
    return pd.DataFrame({"source": SOURCE, "source_id": source_ids.values, "hub": hub, "hub_id": rec.hub_id.values,
                         "match_method": rec.match_method.values, "confidence": rec.confidence.values,
                         "source_version": version})


def _hub_table(hubs: Path | None, name: str) -> gpd.GeoDataFrame | None:
    p = hubs / f"{name}.parquet" if hubs is not None else None
    return gpd.read_parquet(p) if p is not None and p.exists() else None


def _keep_foreign_bridge(hubs: Path | None, twa: pd.DataFrame) -> pd.DataFrame:
    """Snapshot id_bridge rows of every other source unchanged, then this run's twa_kg rows (old twa_kg rows dropped)."""
    p = hubs / "id_bridge.parquet" if hubs is not None else None
    if p is None or not p.exists():
        return twa
    snap = pd.read_parquet(p)
    snap = snap.loc[snap.source != SOURCE, BRIDGE_COLS]
    out = pd.concat([snap, twa], ignore_index=True)
    out["confidence"] = out.confidence.astype(float)
    return out.sort_values(["source", "source_id"]).reset_index(drop=True)


def _keep_snapshot(snap: gpd.GeoDataFrame | None, new: gpd.GeoDataFrame, key: str, cols: list[str]) -> gpd.GeoDataFrame:
    """Snapshot rows unchanged (so a whole-table silver_write does not drop them), then the new TWA rows."""
    if snap is None or snap.empty:
        return new.sort_values(key).reset_index(drop=True)
    snap = snap.to_crs(CRS)
    if "area_m2" in cols and "area_m2" not in snap:
        snap = snap.assign(area_m2=snap.geometry.area)
    snap = snap[[c for c in cols if c in snap.columns]]
    out = pd.concat([snap, new], ignore_index=True)
    return gpd.GeoDataFrame(out, geometry="geometry", crs=CRS)[[c for c in cols if c in out.columns]].sort_values(
        key).reset_index(drop=True)


def run(inputs: dict, params: dict) -> dict:
    d, hubs = Path(inputs["stack"]), inputs.get("hubs")
    hubs = Path(hubs) if hubs is not None else None
    version, min_iou = params["source_version"], params["min_iou"]

    # plots from the landplot subset (LU_DESC/GPR are MP2019 copies; zoning is ura.mp2019_conform's)
    lp = gpd.read_file(d / "landplot.geojson")
    lp = lp.set_crs("EPSG:4326") if lp.crs is None else lp
    lp = lp.to_crs(CRS).sort_values("ogc_fid").reset_index(drop=True)
    lp["ogc_fid"] = lp.ogc_fid.astype(int).astype(str)
    plot_iri = KG + "landplot/" + lp.ogc_fid
    hub_plots = _hub_table(hubs, "plots")
    prec = _reconcile(lp, "twa-p-" + lp.ogc_fid, hub_plots, "plot_id", min_iou)
    lp["plot_id"] = prec.hub_id
    new = (prec.match_method == "exact").values
    plots = gpd.GeoDataFrame({"plot_id": lp.plot_id[new], "area_m2": lp.geometry[new].area, "source_version": version},
                             geometry=lp.geometry[new].values, crs=CRS)
    plots = _keep_snapshot(hub_plots, plots, "plot_id", PLOT_COLS)

    # buildings: footprints (reprojected per source SRID), floors, usage
    b = _csv(d, "buildings.csv")
    parts = [gpd.GeoDataFrame(g, geometry=g.footprint_wkt.map(wkt.loads), crs=f"EPSG:{int(srid)}").to_crs(CRS)
             for srid, g in b.groupby("srid", sort=False)]
    b = gpd.GeoDataFrame(pd.concat(parts), crs=CRS).sort_values("building_iri").reset_index(drop=True)
    b["uuid"] = b.building_iri.map(_local)
    hub_buildings = _hub_table(hubs, "buildings")
    brec = _reconcile(b, "twa-b-" + b.uuid, hub_buildings, "building_id", min_iou)
    b["building_id"] = brec.hub_id

    floors = _csv(d, "floors.csv")
    storeys = (b.building_iri.map(floors.set_index("building_iri").storeys) if floors is not None
               else pd.Series(pd.NA, index=b.index))
    usage = _csv(d, "usage.csv")
    use_type = pd.Series(pd.NA, index=b.index, dtype="object")
    if usage is not None:
        usage["usage_share"] = pd.to_numeric(usage.get("usage_share"), errors="coerce").fillna(1.0)
        top = usage.sort_values("usage_share", ascending=False).drop_duplicates("building_iri")
        use_type = b.building_iri.map(top.set_index("building_iri").usage.map(lambda u: USE_TYPE.get(_local(u), "OTHER")))

    # building -> plot: TWA BuildingIdentificationAgent matches first, centroid-in-plot as fallback
    plot_by_fid = dict(zip(lp.ogc_fid, lp.plot_id))
    lb = _csv(d, "landplot_buildings.csv")
    plot_id = b.uuid.map({r.building_uuid: plot_by_fid.get(str(int(r.ogc_fid))) for r in lb.itertuples()}
                         if lb is not None else {})
    cent = gpd.GeoDataFrame(geometry=b.geometry.centroid, crs=CRS)
    within = gpd.sjoin(cent, plots[["plot_id", "geometry"]], predicate="within", how="left")
    within = within[~within.index.duplicated()]
    plot_id = plot_id.fillna(within.plot_id)

    buildings = gpd.GeoDataFrame({
        "building_id": b.building_id, "plot_id": plot_id.astype("object"),
        "height_m": pd.to_numeric(b.measured_height, errors="coerce"),
        "storeys": pd.to_numeric(storeys, errors="coerce").astype("Int64"),
        "use_type": use_type.astype("object"), "source_version": version}, geometry=b.geometry.values, crs=CRS)
    # TWA is a listed buildings owner, so its rows win for matched hubs; unmatched snapshot buildings pass through.
    if hub_buildings is not None:
        hub_buildings = hub_buildings[~hub_buildings.building_id.isin(buildings.building_id)]
    buildings = _keep_snapshot(hub_buildings, buildings, "building_id", BUILDING_COLS)

    id_bridge = _keep_foreign_bridge(hubs, pd.concat([_bridge(plot_iri, "plot", prec, version),
                                                      _bridge(b.building_iri, "building", brec, version)],
                                                     ignore_index=True))
    return {"plots": plots, "buildings": buildings, "id_bridge": id_bridge}
