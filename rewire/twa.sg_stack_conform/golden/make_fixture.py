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


def hubs(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame({"plot_id": ["MP19-TP-0001", "MP19-TP-0009"], "source_version": "MP2019"},
                     geometry=[box(29401, 28701, 29461, 28761), box(30000, 30000, 30050, 30050)],
                     crs="EPSG:3414").to_parquet(d / "plots.parquet")


if __name__ == "__main__":
    stack(HERE / "tanjong_pagar_synthetic/inputs/stack")
    stack(HERE / "tanjong_pagar_with_ura_hubs/inputs/stack")
    hubs(HERE / "tanjong_pagar_with_ura_hubs/inputs/hubs")
