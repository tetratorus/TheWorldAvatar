"""Point Agents/CEAAgent at the canonical spine transform `cea.building_demand` (no CEAAgent code changed).

CEAAgent speaks building IRIs (`/run`, `/query` with {"iris": [...]}). The spine speaks hub building_ids. This module
translates between them through Silver `id_bridge` (source=twa_kg), so a stack client can keep calling with IRIs while
the numbers come from the spine Gold table that `cea.building_demand` wrote.
"""
from __future__ import annotations

import pandas as pd

SOURCE = "twa_kg"
# Agents/CEAAgent/README.md section 4.3: OntoBuiltEnv usage class -> CEA usage type (copied, not changed).
CEA_USAGE = {
    "Domestic": "MULTI_RES", "SingleResidential": "SINGLE_RES", "MultiResidential": "MULTI_RES",
    "EmergencyService": "HOSPITAL", "FireStation": "HOSPITAL", "PoliceStation": "HOSPITAL", "MedicalCare": "HOSPITAL",
    "Hospital": "HOSPITAL", "Clinic": "HOSPITAL", "Education": "UNIVERSITY", "School": "SCHOOL",
    "UniversityFacility": "UNIVERSITY", "Office": "OFFICE", "RetailEstablishment": "RETAIL",
    "ReligiousFacility": "MUSEUM", "IndustrialFacility": "INDUSTRIAL", "EatingEstablishment": "RESTAURANT",
    "DrinkingEstablishment": "RESTAURANT", "Hotel": "HOTEL", "SportsFacility": "GYM", "CulturalFacility": "MUSEUM",
    "TransportFacility": "INDUSTRIAL", "Non-Domestic": "INDUSTRIAL",
}
CEA_DEFAULT_USAGE = "MULTI_RES"  # CEAAgent default when no usage is found
_UNITS = {"_kwh": "kWh", "_mwh": "MWh", "_m2": "m^2", "_kw": "kW"}


def _rows(id_bridge: pd.DataFrame, hub: str) -> pd.DataFrame:
    return id_bridge[(id_bridge.source == SOURCE) & (id_bridge.hub == hub)]


def iris_to_hub_ids(iris: list[str], id_bridge: pd.DataFrame, hub: str = "building") -> list[str]:
    m = _rows(id_bridge, hub).set_index("source_id").hub_id
    missing = [i for i in iris if i not in m.index]
    if missing:
        raise KeyError(f"IRIs not in id_bridge (run twa.sg_stack_conform first): {missing}")
    return [m[i] for i in iris]


def hub_ids_to_iris(ids, id_bridge: pd.DataFrame, hub: str = "building") -> dict[str, str]:
    r = _rows(id_bridge, hub)
    return dict(zip(r.hub_id, r.source_id)) if ids is None else {k: v for k, v in zip(r.hub_id, r.source_id) if k in set(ids)}


def _unit(col: str, units: dict) -> str:
    return units.get(col) or next((u for s, u in _UNITS.items() if col.endswith(s)), "")


def gold_to_cea_query(gold: pd.DataFrame, id_bridge: pd.DataFrame, iris: list[str], key: str = "building_id",
                      units: dict | None = None) -> dict:
    """Render Gold `cea.building_demand` rows in CEAAgent's `/query` response shape ("ceaOutputs": one dict per IRI)."""
    units = units or {}
    ids = iris_to_hub_ids(iris, id_bridge)
    g = gold.set_index(key)
    cols = [c for c in g.columns if c != "geometry" and pd.api.types.is_numeric_dtype(g[c])]
    outputs = []
    for hid in ids:
        if hid not in g.index:
            outputs.append({})
            continue
        row = g.loc[hid]
        outputs.append({c: f"{round(float(row[c]), 2)} {_unit(c, units)}".strip() for c in cols if pd.notna(row[c])})
    return {"path": "/cea-agent/query", "iris": list(iris), "ceaOutputs": outputs}
