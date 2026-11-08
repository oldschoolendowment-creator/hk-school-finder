# School Finder – Hong Kong Island

A map of every school on Hong Kong Island (kindergartens, primaries, secondaries, international and special schools), with Primary One school nets, admissions details, address search, filters and a shortlist. A Hong Kong version of the England "school finder" app.

## Open it

Double-click `index.html`. It needs an internet connection for the map background and the address search. The teal **HK vs England** button opens `guide.html`, which explains how Hong Kong admissions differ from England.

## Files

- `index.html` — the whole app (map, panel, filters).
- `guide.html` — the "Hong Kong schools for parents used to England" explainer.
- `schools.js` — school data and school net boundaries. **Generated**: don't edit it by hand.
- `tools/prepare_data.py` — rebuilds `schools.js` from the downloads in `data-raw/`.
- `data-raw/` — the original government downloads.

## Data sources (all Hong Kong government open data)

| File in `data-raw/` | What it is | Where from |
|---|---|---|
| `edb_school_locations.json` | Every school, with map position, type, gender, religion, session | [EDB School Location and Information](https://data.gov.hk/en-data/dataset/hk-edb-schinfo-school-location-and-information) (`SCH_LOC_EDB.json`) |
| `poa_nets.geojson` | Primary One school net boundaries | [EDB POA School Net Boundaries](https://data.gov.hk/en-data/dataset/hk-edb-itmospoa-poa-schoolnet-list), downloaded from the CSDI map service as GeoJSON |
| `poa_school_lists.pdf` | P1 discretionary places for each school, by net (POA 2027) | [EDB school lists](https://www.edb.gov.hk/en/edu-system/primary-secondary/spa-systems/primary-1-admission/school-lists/index.html) |
| `sspa.csv` | Which secondary nets each secondary school serves | [EDB SSPA School Net Information](https://data.gov.hk/en-data/dataset/hk-edb-sspa-sspa-schservingnet) |
| `through_train.csv` | Linked "through-train" primary and secondary schools | [EDB Through-train Schools](https://data.gov.hk/en-data/dataset/hk-edb-tts2-through-train-school-list) |
| `dssinfo.csv`, `dssfee.csv` | Direct Subsidy Scheme schools and fees | [EDB DSS schools](https://data.gov.hk/en-data/dataset/hk-edb-dss-dds-school-list) |
| `kg_profiles.csv` | Kindergarten profiles 2025/26 | [EDB Kindergarten Profiles](https://data.gov.hk/en-data/dataset/hk-edb-kgjoinkes-kg-profile) |
| `chsc_primary_profiles.csv` | Primary School Profiles 2026 (English): teaching language, feeder/nominated/through-train secondaries, tests and exams, school day, teachers, classes. Covers government, aided, DSS and some private primaries, not ESF or international | [CHSC Primary School Profiles](https://data.gov.hk/en-data/dataset/chsc-chsc-primary-school-profiles) (`psp_2026_en.csv`) |
| `net.csv` | List of nets and the areas they cover | Same as the net boundaries |

Address search uses the government [Address Lookup Service](https://www.als.gov.hk), live from the browser. Hong Kong has no postcodes, so you type a building, estate or street.

## Refreshing the data

1. Download the newer files above into `data-raw/` with the same names. For the net boundaries, use:
   `https://portal.csdi.gov.hk/server/rest/services/common/edb_rcd_1633320960920_77011/MapServer/0/query?where=1%3D1&outFields=*&outSR=4326&f=geojson`
2. Run `python3 tools/prepare_data.py`. Reading the P1 booklet PDF needs `pip install pypdf`; without it the P1 places figures are left out.

The P1 booklet comes out each August for the following year's entry.

## What is not in it, and why

- **No quality ratings.** Hong Kong publishes no Ofsted-style grades or school league tables, so pins are coloured by type of school.
- **No ESF catchment maps.** ESF assigns schools by home address but doesn't publish its catchments as data.
- **Secondary school profiles** (CHSC publishes these too) aren't added yet; only primaries have a School Profile section.
- **schooland.hk** was considered but not used: its terms forbid republishing its content, and the parts the app needed come from the official profiles above.
