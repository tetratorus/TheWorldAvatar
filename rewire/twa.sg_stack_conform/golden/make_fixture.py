"""Write the synthetic Tanjong Pagar bronze fixtures, shaped like the stack exports (see export_stack_snapshot.py).

Synthetic because the real Singapore stack data is a CARES-only Dropbox. Geometries are authored in EPSG:3414 and
written in the stack's own SRIDs: EPSG:4326 for landplots (landplot.json sridIn), EPSG:24500 for citydb footprints.
  python golden/make_fixture.py && spine freeze transform.yaml <case>
"""
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

HERE = Path(__file__).resolve().parent
KG = "https://www.theworldavatar.com/kg/"
U1, U2, U3 = ("5f0c7a1e-0001-4c1e-9a11-tp0000000001", "5f0c7a1e-0002-4c1e-9a11-tp0000000002",
              "5f0c7a1e-0003-4c1e-9a11-tp0000000003")


def stack(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    plots = gpd.GeoDataFrame({"ogc_fid": [101, 102, 103], "LU_DESC": ["RESIDENTIAL", "COMMERCIAL", "OPEN SPACE"],
                              "GPR": ["2.8", "4.2", "EVA"]},
                             geometry=[box(29400, 28700, 29460, 28760), box(29470, 28700, 29530, 28740),
                                       box(29400, 28770, 29440, 28800)], crs="EPSG:3414").to_crs("EPSG:4326")
    plots.to_file(d / "landplot.geojson", driver="GeoJSON")
    fp = gpd.GeoSeries([box(29410, 28710, 29440, 28740), box(29480, 28705, 29520, 28735),
                        box(29445, 28745, 29455, 28755)], crs="EPSG:3414").to_crs("EPSG:24500")
    pd.DataFrame({"building_iri": [KG + "Building/" + u for u in (U1, U2, U3)], "footprint_wkt": fp.to_wkt(),
                  "srid": 24500, "measured_height": [36.5, 60.0, None]}).to_csv(d / "buildings.csv", index=False)
    pd.DataFrame({"building_iri": [KG + "Building/" + U1, KG + "Building/" + U2], "storeys": [12, 15]}).to_csv(
        d / "floors.csv", index=False)
    obe = "https://www.theworldavatar.com/kg/ontobuiltenv/"
    pd.DataFrame({"building_iri": [KG + "Building/" + U1, KG + "Building/" + U2, KG + "Building/" + U2],
                  "usage": [obe + "MultiResidential", obe + "Office", obe + "RetailEstablishment"],
                  "usage_share": [1.0, 0.7, 0.3]}).to_csv(d / "usage.csv", index=False)
    pd.DataFrame({"ogc_fid": [101, 102], "building_uuid": [U1, U2]}).to_csv(d / "landplot_buildings.csv", index=False)


def _bridge(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["source", "source_id", "hub", "hub_id", "match_method", "confidence",
                                       "source_version"])


def hubs(d: Path) -> None:
    """Lake snapshot after ura.mp2019_conform: MP2019 plots + their id_bridge row (must survive the TWA run)."""
    d.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame({"plot_id": ["MP19-TP-0001", "MP19-TP-0009"], "source_version": "MP2019"},
                     geometry=[box(29401, 28701, 29461, 28761), box(30000, 30000, 30050, 30050)],
                     crs="EPSG:3414").to_parquet(d / "plots.parquet")
    _bridge([("ura_mp2019", "kml_4711", "plot", "MP19-TP-0001", "exact", 1.0, "MP2019")]).to_parquet(
        d / "id_bridge.parquet", index=False)


def building_hubs(d: Path) -> None:
    """Snapshot after ura.mp2019_conform + duct.bdp_conform + an older TWA run.

    DUCT-B-0001 overlaps TWA building 1 (IoU 841/959) so TWA's row wins under that hub id; DUCT-B-0099 matches nothing
    and must pass through. The stale twa_kg row is replaced by this run's twa_kg rows; all other bridge rows survive.
    """
    hubs(d)
    gpd.GeoDataFrame({"building_id": ["DUCT-B-0001", "DUCT-B-0099"], "plot_id": ["MP19-TP-0001", "MP19-TP-0009"],
                      "height_m": [35.0, 12.0], "storeys": pd.array([11, 4], dtype="Int64"),
                      "use_type": ["RESIDENTIAL", "OTHER"], "year_built": pd.array([1998, 1985], dtype="Int64"),
                      "source_version": "duct-bdp-2023"},
                     geometry=[box(29411, 28711, 29441, 28741), box(30010, 30010, 30030, 30030)],
                     crs="EPSG:3414").to_parquet(d / "buildings.parquet")
    _bridge([("ura_mp2019", "kml_4711", "plot", "MP19-TP-0001", "exact", 1.0, "MP2019"),
             ("duct_bdp", "BDP-000001", "building", "DUCT-B-0001", "exact", 1.0, "duct-bdp-2023"),
             ("duct_bdp", "BDP-000099", "building", "DUCT-B-0099", "exact", 1.0, "duct-bdp-2023"),
             ("cea_zone", "B1001", "building", "DUCT-B-0001", "manual", None, "cea-3.39"),
             ("twa_kg", KG + "Building/stale-uuid", "building", "twa-b-stale-uuid", "exact", 1.0, "twa-sg-stack-old")]
            ).to_parquet(d / "id_bridge.parquet", index=False)


if __name__ == "__main__":
    stack(HERE / "tanjong_pagar_synthetic/inputs/stack")
    stack(HERE / "tanjong_pagar_with_ura_hubs/inputs/stack")
    hubs(HERE / "tanjong_pagar_with_ura_hubs/inputs/hubs")
    stack(HERE / "tanjong_pagar_with_building_hubs/inputs/stack")
    building_hubs(HERE / "tanjong_pagar_with_building_hubs/inputs/hubs")
