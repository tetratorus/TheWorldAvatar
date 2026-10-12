from pathlib import Path

import pytest
from spine.golden import load_case_inputs, run_golden
from spine.transform import invoke, load_descriptor, resolve_params

HERE = Path(__file__).resolve().parents[1]
DESC = load_descriptor(HERE / "transform.yaml")
KG = "https://www.theworldavatar.com/kg/"


def _run(case):
    return invoke(DESC, load_case_inputs(DESC, HERE / "golden" / case), resolve_params(DESC, {}))


def test_golden_cases_pass():
    res = run_golden(DESC)
    assert res and all(r.passed for r in res), [r.messages for r in res]


def test_plots_zoning_hand_checked():
    out = _run("tanjong_pagar_synthetic")
    plots = out["plots"].set_index("plot_id")
    assert out["plots"].crs.to_epsg() == 3414
    assert plots.area_m2.to_dict() == pytest.approx({"twa-p-101": 3600, "twa-p-102": 2400, "twa-p-103": 1200}, rel=1e-6)
    z = out["zoning"].set_index("plot_id")
    assert z.gross_plot_ratio["twa-p-101"] == 2.8 and z.gross_plot_ratio.isna()["twa-p-103"]  # "EVA" -> null


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
    assert set(out["id_bridge"].source) == {"twa_kg"}


def test_reuses_existing_ura_hub():
    out = _run("tanjong_pagar_with_ura_hubs")
    br = out["id_bridge"].set_index("source_id")
    row = br.loc[KG + "landplot/101"]
    assert (row.hub_id, row.match_method) == ("MP19-TP-0001", "spatial_overlap")
    assert row.confidence == pytest.approx(3481 / 3719, rel=1e-4)              # IoU of 59x59 overlap
    assert out["buildings"].set_index("building_id").loc[
        "twa-b-5f0c7a1e-0001-4c1e-9a11-tp0000000001", "plot_id"] == "MP19-TP-0001"
