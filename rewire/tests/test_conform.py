from pathlib import Path

import pandas as pd
import pytest
from spine.golden import load_case_inputs, run_golden
from spine.transform import invoke, load_descriptor, resolve_params

HERE = Path(__file__).resolve().parents[1] / "twa.sg_stack_conform"
DESC = load_descriptor(HERE / "transform.yaml")
KG = "https://www.theworldavatar.com/kg/"


def _run(case):
    return invoke(DESC, load_case_inputs(DESC, HERE / "golden" / case), resolve_params(DESC, {}))


def test_golden_cases_pass():
    res = run_golden(DESC)
    assert res and all(r.passed for r in res), [r.messages for r in res]


def test_plots_hand_checked():
    out = _run("tanjong_pagar_synthetic")
    plots = out["plots"].set_index("plot_id")
    assert out["plots"].crs.to_epsg() == 3414
    assert plots.area_m2.to_dict() == pytest.approx({"twa-p-101": 3600, "twa-p-102": 2400, "twa-p-103": 1200}, rel=1e-6)


def test_no_zoning_output():
    # zoning belongs to ura.mp2019_conform (LAYERS.md); silver_write would replace the MP2019 table
    assert "zoning" not in _run("tanjong_pagar_synthetic")
    assert [o["name"] for o in DESC.data["outputs"]] == ["plots", "buildings", "id_bridge"]


def test_buildings_and_bridge():
    out = _run("tanjong_pagar_synthetic")
    b = out["buildings"].set_index("building_id")
    first = "twa-b-5f0c7a1e-0001-4c1e-9a11-tp0000000001"
    assert b.loc[first, "storeys"] == 12 and b.loc[first, "use_type"] == "RESIDENTIAL"
    assert b.loc[first].geometry.area == pytest.approx(900, rel=1e-6)          # EPSG:24500 -> 3414 round trip
    assert b.loc["twa-b-5f0c7a1e-0002-4c1e-9a11-tp0000000002", "use_type"] == "OFFICE"  # max usage share
    assert b.loc["twa-b-5f0c7a1e-0003-4c1e-9a11-tp0000000003", "plot_id"] == "twa-p-101"  # centroid fallback
    br = out["id_bridge"].set_index("source_id")
    assert br.loc[KG + "landplot/101", "hub_id"] == "twa-p-101"
    assert br.loc[KG + "Building/5f0c7a1e-0001-4c1e-9a11-tp0000000001", "hub"] == "building"
    assert len(br) == 6                                                         # 3 landplot + 3 building IRIs


def test_reuses_existing_ura_hub():
    out = _run("tanjong_pagar_with_ura_hubs")
    br = out["id_bridge"].set_index("source_id")
    row = br.loc[KG + "landplot/101"]
    assert (row.hub_id, row.match_method) == ("MP19-TP-0001", "spatial_overlap")
    assert row.confidence == pytest.approx(3481 / 3719, rel=1e-4)              # IoU of 59x59 overlap
    assert out["buildings"].set_index("building_id").loc[
        "twa-b-5f0c7a1e-0001-4c1e-9a11-tp0000000001", "plot_id"] == "MP19-TP-0001"


def test_snapshot_plots_survive_whole_table_write():
    # Lake.silver_write replaces the table: every MP2019 hub row must come back unchanged, plus only unmatched TWA plots
    plots = _run("tanjong_pagar_with_ura_hubs")["plots"].set_index("plot_id")
    assert sorted(plots.index) == ["MP19-TP-0001", "MP19-TP-0009", "twa-p-102", "twa-p-103"]
    assert plots.source_version.to_dict() == {"MP19-TP-0001": "MP2019", "MP19-TP-0009": "MP2019",
                                              "twa-p-102": "twa-sg-stack", "twa-p-103": "twa-sg-stack"}
    assert plots.loc["MP19-TP-0001"].geometry.bounds == (29401, 28701, 29461, 28761)  # owner geometry, not TWA's


def _key(df):
    return df.set_index(["source", "source_id"]).sort_index()


def test_foreign_bridge_rows_survive_whole_table_write():
    # id_bridge is replaced as a whole table too: every non-twa_kg snapshot row must come back unchanged (rule 9)
    for case in ("tanjong_pagar_with_ura_hubs", "tanjong_pagar_with_building_hubs"):
        snap = pd.read_parquet(HERE / "golden" / case / "inputs" / "hubs" / "id_bridge.parquet")
        out = _run(case)["id_bridge"]
        foreign = snap[snap.source != "twa_kg"]
        assert len(foreign) and set(foreign.source) <= set(out.source)
        pd.testing.assert_frame_equal(_key(out[out.source != "twa_kg"]), _key(foreign), check_dtype=False)
        twa = out[out.source == "twa_kg"]
        assert len(twa) == 6 and set(twa.source_version) == {"twa-sg-stack"}  # stale twa_kg rows replaced
        assert not out.duplicated(["source", "source_id"]).any()


def test_snapshot_buildings_union():
    # unmatched snapshot buildings pass through unchanged; on a matched hub TWA's row wins under the existing hub id
    out = _run("tanjong_pagar_with_building_hubs")
    b = out["buildings"].set_index("building_id")
    assert sorted(b.index) == ["DUCT-B-0001", "DUCT-B-0099", "twa-b-5f0c7a1e-0002-4c1e-9a11-tp0000000002",
                               "twa-b-5f0c7a1e-0003-4c1e-9a11-tp0000000003"]
    assert (b.loc["DUCT-B-0001", "source_version"], b.loc["DUCT-B-0001", "height_m"]) == ("twa-sg-stack", 36.5)
    assert b.loc["DUCT-B-0001"].geometry.area == pytest.approx(900, rel=1e-6)   # TWA footprint, not DUCT's 30x30+1
    assert (b.loc["DUCT-B-0099", "source_version"], b.loc["DUCT-B-0099", "year_built"]) == ("duct-bdp-2023", 1985)
    assert b.loc["DUCT-B-0099"].geometry.bounds == (30010, 30010, 30030, 30030)
    row = out["id_bridge"].set_index("source_id").loc[KG + "Building/5f0c7a1e-0001-4c1e-9a11-tp0000000001"]
    assert (row.hub_id, row.match_method) == ("DUCT-B-0001", "spatial_overlap")
    assert row.confidence == pytest.approx(841 / 959, rel=1e-4)
