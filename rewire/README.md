# rewire/ — The World Avatar on the sg-urban-spine

This folder plugs The World Avatar (TWA) Singapore stack into [sg-urban-spine](https://github.com/tetratorus/saas-middleware/tree/sg-urban-spine), the
shared model shell for the URA "Rewire, don't rewrite" demo. **No upstream TWA code is changed.** Everything here sits beside it.

```
pip install 'git+https://github.com/tetratorus/saas-middleware@sg-urban-spine' pytest
spine --path rewire validate && spine --path rewire test && python -m pytest rewire/tests
```

| Path | Spine role | What it does |
|---|---|---|
| `twa.sg_stack_conform/` | conformer (Bronze → Silver) | TWA Singapore stack snapshot → Silver `buildings`, `plots` + `id_bridge` (no `zoning`, see below) |
| `twa.sg_stack_conform/export_stack_snapshot.py` | Bronze ingest | Dumps a running stack (PostGIS + Ontop) into the Bronze layout. **Untested.** |
| `agents/cea_agent_bridge.py` | transform adapter (Gold ↔ agent API) | Points CEAAgent at `cea.building_demand`: IRIs ↔ hub ids, Gold → `/query` response shape |
| `agents/gfa_agent_bridge.py`, `agents/gfa_allowable.obda` | transform adapter / view | Points the landplot `ref_gfa` layer and GFAAgent at `gfa.allowable` Gold. Ontop publishes it as `ontoplot:hasMaximumPermittedGFA` |
| `tests/` | pytest | Golden + adapter tests for the conformer and both agent bridges (`pytest rewire/tests`) |

## Data used: synthetic fixtures only
The real Singapore stack data sits in a CARES-only Dropbox (`Deploy/stacks/Singapore/README.md`). Building the Java agents also
needs Maven GitHub-packages credentials. Neither was available, so the golden cases use a **synthetic 3-plot / 3-building fixture
in Tanjong Pagar**. `twa.sg_stack_conform/golden/make_fixture.py` writes it in the stack's own shapes and SRIDs: landplots as
EPSG:4326 GeoJSON (as in `landplot.json` `sridIn`) and citydb footprints in EPSG:24500 (as in `buildings.json` `sridIn`). The
adapter reprojects both to EPSG:3414.

## IDs: TWA IRIs → spine hubs (GERS pattern)
| TWA IRI (`id_bridge.source = twa_kg`, `source_id`) | hub | hub_id |
|---|---|---|
| `https://www.theworldavatar.com/kg/landplot/{ogc_fid}` (landplot.json virtual table) | plot | existing hub if IoU ≥ `min_iou` with a supplied hub snapshot (`spatial_overlap`, confidence = IoU), else `twa-p-{ogc_fid}` (`exact`) |
| `https://www.theworldavatar.com/kg/Building/{uuid}` (CEAAgent / gfa.obda) | building | existing hub by IoU, else `twa-b-{uuid}` |

`buildings.plot_id` comes from the stack's BuildingIdentificationAgent `landplot_buildings` table. Where that table has no row,
the adapter falls back to "the building's centroid lies inside the plot". The optional Bronze input `hubs` is a snapshot of
lake's current Silver `plots`, `buildings` **and `id_bridge`** (for example after `ura.mp2019_conform` and `duct.bdp_conform`). It lets
TWA features reuse those hub ids instead of creating parallel keys, and it is what keeps the other sources' rows alive (below).

## Which Silver tables this writes, and why not `zoning`
LAYERS.md lists `twa.sg_stack_conform` for **buildings** and gives `plots`/`zoning` to `ura.mp2019_conform`. The stack's landplot
`LU_DESC` and `GPR` are copies of the URA Master Plan 2019, so a TWA `zoning` table would only duplicate MP2019, and because
`Lake.silver_write` replaces whole tables it would wipe the MP2019 one. The same whole-table replace applies to every output, so
all three are union-preserving against the `hubs` snapshot:
- **No `zoning` output.** GFA and anything else that needs GPR read `ura.mp2019_conform`'s Silver `zoning`.
- **`plots` is still emitted** (the task asks for plots, and the landplot IRIs need a plot hub to bridge to). It is
  union-preserving: every row of the `hubs` snapshot comes back unchanged (MP2019 geometry and `source_version` win), and only
  TWA landplots that matched no existing hub are added as `twa-p-*`. Covered by the `tanjong_pagar_with_ura_hubs` golden and
  `test_snapshot_plots_survive_whole_table_write`.
- **`buildings`** works the same way. TWA rows win for matched hubs (TWA is a listed buildings owner; the hub id is kept, the
  row's attributes are TWA's), and unmatched snapshot buildings (e.g. from `duct.bdp_conform`) pass through unchanged. Covered
  by the `tanjong_pagar_with_building_hubs` golden and `test_snapshot_buildings_union`.
- **`id_bridge`** is union-preserving too. Every snapshot row whose `source` is not `twa_kg` (`ura_mp2019`, `duct_bdp`,
  `cea_zone`, ...) comes back unchanged, and only the `twa_kg` rows are replaced by this run's rows. Covered by both hub goldens
  and `test_foreign_bridge_rows_survive_whole_table_write`.
- **Always run it with a current `hubs` snapshot that includes `id_bridge.parquet`** as well as `plots`/`buildings`. Without one
  (or with a stale one) the three tables hold TWA rows only, and **every other source's `id_bridge` rows are deleted**, which
  breaks LAYERS.md rule 9 (IDs bridge, never fork) for those sources.

## CEAAgent → `cea.building_demand`
CEAAgent (Java + its own CEA Python workflow) stays the stack-side runtime. The spine-facing contract is `cea.building_demand`
(owned by the CityEnergyAnalyst fork). To repoint it:
1. Run `twa.sg_stack_conform`. Silver now has buildings and `id_bridge` rows for the CEAAgent IRIs.
2. Run `spine run cea.building_demand`. Gold is keyed by `building_id`.
3. Stack clients keep sending `{"iris": [...]}`. `cea_agent_bridge.iris_to_hub_ids` resolves the IRIs and
   `gold_to_cea_query` answers in CEAAgent's `/query` shape (`ceaOutputs`), using Gold instead of re-running CEA.
`CEA_USAGE` copies CEAAgent's OntoBuiltEnv → CEA usage table (README §4.3) so the transform can use the same usage mapping.

## GFAAgent / landplot layer → `gfa.allowable`
GFAAgent computes **built** GFA (footprint area × `hasNumberOfFloors`, written to `ontobuiltenv:hasGFA`), which is a different
quantity. It is left alone. **Allowable** GFA was computed inline in `Deploy/stacks/Singapore/custom_sql_scripts/landplot_layer.sql`
(`ref_gfa` = GPR × `ST_Area`). `gfa_agent_bridge.gold_to_landplot_ref_gfa` maps Gold `gfa.allowable` (keyed by `plot_id`) back to
landplot IRIs. Loaded as `spine_gold.gfa_allowable`, it replaces the `ref_gfa` CTE, and `gfa_allowable.obda` exposes it as
`ontoplot:hasMaximumPermittedGFA/om:hasValue/om:hasNumericalValue`. `stack_ref_gfa` reproduces the old SQL so the two can be
compared. Planar SVY21 area and the stack's spheroid `ST_Area(geog)` differ by about 1e-4 relative.

## Licence / commercial use
The TWA code is MIT (`LICENSE.txt`). The Singapore stack *data* has its own source licences (URA Master Plan, OSM ODbL, CityGML
provider), so the descriptor declares `commercial_use: review`.

## Readiness (NOAA RL)
`twa.sg_stack_conform` is at **RL4**. Evidence: `spine --path rewire validate` and `spine --path rewire test` pass (3 golden
cases), `pytest rewire/tests` passes (14 tests), and `spine run` into a scratch lake seeded with a `ura_mp2019` `id_bridge` row
keeps that row next to the 6 `twa_kg` rows and keeps both MP2019 hub plots, all on synthetic fixtures only. Gaps: no run on the
real stack, the export script is untested, and correct sharing of `plots`/`buildings`/`id_bridge` needs a current hubs snapshot
(including `id_bridge`) as input, because the spine has no per-source merge. See `transform.yaml`.

## Upstream changes
None.

## Ontology notes
The Silver ↔ TWA ontology mapping is validated in tetratorus/ontology `rewire/`. TWA-side inconsistencies were found there: `gfa.obda`
uses `plot:hasCalculatedGFA` and `plot:containsBuilding`, which are not in OntoPlot, and `building_usage.obda` uses
`hasUsageLabel`, which is not in OntoBuiltEnv. They are reported, not changed.
