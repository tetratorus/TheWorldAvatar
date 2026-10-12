"""Dump a running Deploy/stacks/Singapore stack into the bronze layout that adapter.py reads.

UNTESTED: this was written without access to a running stack. The queries reuse the stack's own SQL/SPARQL:
landplot.json virtual table, GFAAgent total_area_query.sql (footprints via cityobject_genericattrib 'iri'),
GFACalculation.java (env:hasNumberOfFloors/env:hasValue) and the CEAAgent usage query (hasPropertyUsage / hasUsageShare).
  python export_stack_snapshot.py --pg postgresql://... --ontop http://localhost:3838/ontop/sparql --out snap/
  spine bronze-add twa_sg_stack snap/
Credentials come from the environment/CLI; never commit them.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pandas as pd

BUILDINGS_SQL = """
SELECT a.urival AS building_iri, ST_AsText(ST_Union(sg.geometry)) AS footprint_wkt,
       ST_SRID(ST_Union(sg.geometry)) AS srid, b.measured_height
FROM citydb.building b
JOIN citydb.surface_geometry sg ON b.lod0_footprint_id = sg.parent_id
JOIN citydb.cityobject_genericattrib a ON a.cityobject_id = b.id AND a.attrname = 'iri'
GROUP BY a.urival, b.measured_height
"""
LANDPLOT_BUILDINGS_SQL = "SELECT ogc_fid, building_uuid FROM landplot_buildings"
PREFIX = "PREFIX env: <https://www.theworldavatar.com/kg/ontobuiltenv/>\n"
FLOORS_RQ = PREFIX + "SELECT ?building_iri ?storeys WHERE { ?building_iri env:hasNumberOfFloors/env:hasValue ?storeys }"
USAGE_RQ = PREFIX + ("SELECT ?building_iri ?usage ?usage_share WHERE { ?building_iri env:hasPropertyUsage ?u . "
                     "?u a ?usage . OPTIONAL { ?u env:hasUsageShare ?usage_share } }")


def sparql(endpoint: str, query: str) -> pd.DataFrame:
    import requests
    r = requests.post(endpoint, data={"query": query}, headers={"Accept": "application/sparql-results+json"},
                      timeout=600)
    r.raise_for_status()
    rows = r.json()["results"]["bindings"]
    return pd.DataFrame([{k: v["value"] for k, v in row.items()} for row in rows])


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pg", required=True, help="postgres URL of the stack's postgis (e.g. from env)")
    ap.add_argument("--ontop", required=True, help="Ontop SPARQL endpoint")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    import sqlalchemy
    a.out.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ogr2ogr", "-f", "GeoJSON", "-t_srs", "EPSG:4326", str(a.out / "landplot.geojson"),
                    f"PG:{a.pg}", "-sql", 'SELECT ogc_fid, "LU_DESC", "GPR", "lod1Geometry" FROM landplot'], check=True)
    eng = sqlalchemy.create_engine(a.pg)
    pd.read_sql(BUILDINGS_SQL, eng).to_csv(a.out / "buildings.csv", index=False)
    pd.read_sql(LANDPLOT_BUILDINGS_SQL, eng).to_csv(a.out / "landplot_buildings.csv", index=False)
    sparql(a.ontop, FLOORS_RQ).to_csv(a.out / "floors.csv", index=False)
    sparql(a.ontop, USAGE_RQ).to_csv(a.out / "usage.csv", index=False)


if __name__ == "__main__":
    main()
