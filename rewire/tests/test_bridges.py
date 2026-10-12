import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))
from cea_agent_bridge import gold_to_cea_query, iris_to_hub_ids
from gfa_agent_bridge import gold_to_landplot_ref_gfa, stack_ref_gfa
from spine.golden import load_case_inputs
from spine.transform import invoke, load_descriptor, resolve_params

CONFORM = Path(__file__).resolve().parents[1] / "twa.sg_stack_conform"
KG = "https://www.theworldavatar.com/kg/"
B1 = KG + "Building/5f0c7a1e-0001-4c1e-9a11-tp0000000001"


@pytest.fixture(scope="module", params=["tanjong_pagar_synthetic", "tanjong_pagar_with_ura_hubs"])
def silver(request):
    d = load_descriptor(CONFORM / "transform.yaml")
    return invoke(d, load_case_inputs(d, CONFORM / "golden" / request.param), resolve_params(d, {}))


def test_cea_query_shape_via_id_bridge(silver):
    hid = iris_to_hub_ids([B1], silver["id_bridge"])[0]
    gold = pd.DataFrame({"building_id": [hid], "annual_electricity_kwh": [123456.789], "roof_pv_area_m2": [800.0]})
    resp = gold_to_cea_query(gold, silver["id_bridge"], [B1])
    assert resp["iris"] == [B1]
    assert resp["ceaOutputs"] == [{"annual_electricity_kwh": "123456.79 kWh", "roof_pv_area_m2": "800.0 m^2"}]


def test_unknown_iri_rejected(silver):
    with pytest.raises(KeyError):
        iris_to_hub_ids([KG + "Building/not-there"], silver["id_bridge"])


def test_gfa_allowable_back_to_landplot_iris(silver):
    # stand-in for Silver zoning (owned by ura.mp2019_conform): the fixture's MP2019 GPR per landplot ("EVA" -> null)
    hub = silver["id_bridge"][silver["id_bridge"].hub == "plot"].set_index("source_id").hub_id
    zoning = pd.DataFrame({"plot_id": [hub[KG + f"landplot/{f}"] for f in (101, 102, 103)],
                           "gross_plot_ratio": [2.8, 4.2, None]})
    # stand-in for Gold gfa.allowable (owned by 3d-landuse-planning): GPR x area, as in the spine toy example
    ref = stack_ref_gfa(silver["plots"], zoning)
    gold = pd.DataFrame({"plot_id": ref.index, "allowable_gfa_m2": ref.values})
    out = gold_to_landplot_ref_gfa(gold, silver["id_bridge"]).set_index("iri").ref_gfa
    assert out.to_dict() == pytest.approx({KG + "landplot/101": 3600 * 2.8, KG + "landplot/102": 2400 * 4.2,
                                           KG + "landplot/103": 0.0}, rel=1e-6)
