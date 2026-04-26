# EU - Co-Decision Procedure (COD) Scrapper

This `Readme` explains the detailed functionality of the scrapper. The document is structured as follows:

- `INSTALLING DEPENDENCIES`
- `ROOT STRUCTURE`
- `PIPELINE GUIDE`
- `STEPS`
- `NOTES`

## INSTALLING DEPENDENCIES AND RUN GUIDE

From the project root, activate the conda environment and install the required packages:

```bash
conda activate env
pip install -r requirements.txt
```

Move into the scraper project folder and run the incremental pipeline:

```bash
cd scrapper
python run_incremental_pipeline.py
```

## ROOT STRUCTURE

The project is structured as a scraper module, with the folders:

```text
eu_legislation/
    scrapper/
        __init__.py
        bld/
            __init__.py
        functions/
            __init__.py
        scripts/
            __init__.py
        run_incremental_pipeline.py
```

## PIPELINE GUIDE

### Pipeline Order

The full-pipeline order is:

```text
01. committee_dictionary
02. scrape_cod_procedures
03. meta_table
04. wide_meta
05. timeline_table
06. transparency_table
07. com_vote_info
08. com_vote_procedure
09. com_roll_call
10. other_format_com_vote_procedure
11. scrape_council_votes_meta
12. scrape_council_lop_eulex_link
13. scrape_council_lop_pres_con_links
14. scrape_council_lop_pres_con
15. scrape_council_lop_meeting-docs
16. scrape_voted_amendments_in_plenary
17. scrape_all_amendments
18. scrape_ep_final_vote_results
```

### Script-to-Function Mapping

| No. | Script | Function file | Bld input deps | Bld output(s) |
|---|---|---|---|---|
| 1. | `scripts/create_committee_dictionary.py` | `functions/create_committee_dictionary.py` |  | `bld/committee_dictionary.csv`, `bld/committee_dictionary.json` |
| 2. | `scripts/scrape_cod_procedures.py` | `functions/scrape_cod_procedures.py` |  | `bld/oeil_cod_procedures.csv` |
| 3. | `scripts/create_meta_table.py` | `functions/create_meta_table.py` | `bld/oeil_cod_procedures.csv` | `bld/meta_table.csv`, `bld/meta_table.json` |
| 4. | `scripts/create_wide_meta.py` |  | `bld/oeil_cod_procedures.csv`, `bld/meta_table.csv`, `bld/meta_table.json` | `bld/wide_meta.csv`, `bld/meta_council_info.csv` |
| 5. | `scripts/create_timeline_table.py` | `functions/create_timeline_table.py` | `bld/oeil_cod_procedures.csv` | `bld/timeline_table.csv`, `bld/timeline_table.json` |
| 6. | `scripts/create_transparency_table.py` | `functions/create_transparency_table.py` | `bld/oeil_cod_procedures.csv` | `bld/transparency_table.csv`, `bld/transparency_table.json` |
| 7. | `scripts/create_com_vote_info.py` | `functions/create_com_vote_info.py` | `bld/timeline_table.csv` | `bld/committee_vote_info.csv`, `bld/committee_vote_info.json` |
| 8. | `scripts/create_com_vote_procedure.py` | `functions/create_com_vote_procedure.py` | `bld/timeline_table.csv`, `bld/committee_vote_info.csv` | `bld/committee_vote_procedure_table.csv`, `bld/committee_vote_procedure_table.json` |
| 9. | `scripts/create_com_roll_call.py` | `functions/create_com_roll_call.py` | `bld/timeline_table.csv`, `bld/committee_vote_info.csv` | `bld/committee_roll_call_table.csv`, `bld/committee_roll_call_table.json` |
| 10. | `scripts/create_other_format_com_vote_procedure.py` | `functions/create_other_format_com_vote_procedure.py` | `bld/timeline_table.csv`, `bld/committee_vote_info.csv`, `bld/committee_dictionary.csv` | `bld/committee_other_format_procedure_table.csv`, `bld/committee_other_format_procedure_table.json` |
| 11. | `scripts/scrape_council_votes_meta.py` | `functions/scrape_council_votes_meta.py` |  | `bld/council_votes.csv`, `bld/council_votes_meta.csv`, `bld/council_votes.json`, `bld/council_votes_meta.json` |
| 12. | `scripts/create_council_lop_eulex_link.py` |  | `bld/timeline_table.csv` | `bld/timeline_table_eulex_link_check.csv` |
| 13. | `scripts/create_council_lop_pres_con_links.py` |  | `bld/timeline_table_eulex_link_check.csv` | `bld/pres_con_links.csv` |
| 14. | `scripts/create_council_lop_pres_con.py` | `functions/create_council_lop_pres_con.py` | `bld/pres_con_links.csv` | `bld/council_lop_pres_con.csv`, `bld/council_lop_pres_con.json` |
| 15. | `scripts/create_council_lop_meeting_doc.py` | `functions/create_council_lop_meeting_doc.py` |  | `bld/council_lop_out_docs.csv` |
| 16. | `scripts/create_voted_amendments.py` | `functions/create_voted_amendments.py` | `bld/timeline_table.csv` | `bld/voted_amendments_all.csv`, `bld/failed_voted_amendments.csv` |
| 17. | `scripts/create_all_amendments.py` | `functions/create_all_amendments.py` | `bld/timeline_table.csv` | `bld/proposed_amendments_all.csv`, `bld/all_amendments_document_links.csv`, `bld/failed_all_amendments_pdf_text.csv`, `bld/failed_all_amendments_parsing.csv` |
| 18. | `scripts/create_ep_final_vote_results.py` | `functions/create_ep_final_vote_results.py` | `bld/timeline_table.csv` | `bld/final_vote_ep_extracted.csv`, `bld/failed_ep_vote_extractions.csv` |

## STEPS


### 01. Build committee dictionary

#### Task name

`committee_dictionary`

#### Script

`scripts/create_committee_dictionary.py`

#### Function file

`functions/create_committee_dictionary.py`

#### Outputs

- `bld/committee_dictionary.csv`
- `bld/committee_dictionary.json`

#### Purpose

Builds a dictionary of European Parliament committee names/codes.

Output example:

| committee_code | committee | committee_type |
|---|---|---|
| `EUDS` | European Democracy Shield | Special committee |
| `HOUS` | Housing Crisis in the EU | Special committee |
| `AFCO` | Constitutional Affairs | Standing committee |
| `AFET` | Foreign Affairs | Standing committee |
| `AGRI` | Agriculture and Rural Development | Standing committee |
| `BUDG` | Budgets | Standing committee |
| `CONT` | Budgetary Control | Standing committee |
| `CULT` | Culture and Education | Standing committee |
| `...` | `...` | `...` |


#### Used later by

- `other_format_com_vote_procedure`

---

### 02. Scrape COD procedures

#### Task name

`scrape_cod_procedures`

#### Script

`scripts/scrape_cod_procedures.py`

#### Function file

`functions/scrape_cod_procedures.py`

#### Outputs

- `bld/oeil_cod_procedures.csv`

#### Purpose

Scrapes the list of Ordinary Legislative Procedure / COD procedures from OEIL:
`https://oeil.europarl.europa.eu/oeil/en/search?fullText.mode=EXACT_WORD`.
All the procedures are gathered in this step.

Output example:

| reference | title | stage | committees | url |
|---|---|---|---|---|
| `2025/0399(COD)` | Trans-European energy infrastructure: guidelines | `***I` | Industry, Research and Energy | `https://oeil.europarl.europa.eu/oeil/en/procedure-file?reference=2025/0399(COD)` |
| `2025/0397(COD)` | Simplification of some requirements and reduction of administrative burden in the areas of batteries and industrial emissions reporting (Omnibus VIII on environmental legislation) | `***I` | Environment, Climate and Food Safety | `https://oeil.europarl.europa.eu/oeil/en/procedure-file?reference=2025/0397(COD)` |
|`...`|`...`|`...`|`...`|`...`|


#### Used later by

- `meta_table`
- `wide_meta`
- `timeline_table`
- `transparency_table`

---

### 03. Build meta table

#### Task name

`meta_table`

#### Script

`scripts/create_meta_table.py`

#### Function file

`functions/create_meta_table.py`

#### Depends on

- `scrape_cod_procedures`

#### Inputs

- `bld/oeil_cod_procedures.csv`

#### Outputs

- `bld/meta_table.csv`
- `bld/meta_table.json`

#### Purpose

Builds the metadata table for procedures. This file follows one row per `meta_column`. `procedure` is repeated, making this a long table. Currently this step is done for a sample list of procedures: 

```
procedures = [
    '2021/0366(COD)',
    '2014/0011(COD)',
    '2012/0364(COD)',
    '2010/0380(COD)',
    '2010/0377(COD)',
    '2007/0295(COD)',
    '2000/0073(COD)',
    '1994/0272(COD)',
    '2011/0465(COD)',
    '2011/0439(COD)',
    '2012/0358(COD)',
    '2013/0303(COD)',
    '2014/0213(COD)',
    '2014/0091(COD)',
    '2015/0284(COD)',
    '2015/0287(COD)',
    '2016/0414(COD)',
    '2016/0224B(COD)',
    '2017/0354(COD)',
    '2014/0004(COD)',
    '2018/0298(COD)',
    '2019/0002(COD)',
    '2020/0347(COD)',
    '2020/0262(COD)',
    # Add more references as needed
]
```

Output example:

| year | policy_number | procedure | meta_column | value |
|---:|---|---|---|---|
| `2021` | `0366(COD)` | `2021/0366(COD)` | `title` | Deforestation Regulation |
| `2021` | `0366(COD)` | `2021/0366(COD)` | `policy_id` | `2021/0366(COD)` |
| `2021` | `0366(COD)` | `2021/0366(COD)` | `procedure_type` | COD - Ordinary legislative procedure (ex-codecision procedure) |
| `...` | `...` | `...` | `...` | `...` |

`meta_column` includes the following:

- `title`
- `policy_id`
- `procedure_type`
- `act_type`
- `action_i`
- `regulation_i`
- `procedure_i`
- `procedure_link_i`
- `subject_code_i`
- `subject_i`
- `status`
- `EP lead committee code`
- `EP lead committee`
- `Rapporteur`
- `Rapporteur group`
- `Rapporteur link`
- `Appointment date`
- `Shadow rapporteur_i`
- `Shadow rapporteurs group_i`
- `Shadow rapporteurs link_i`
- `Committee for opinion_i`
- `Committee for opinion_i code`
- `Com_op_i rapporteurs`
- `Com_op_i rapporteurs group`
- `Com_op_i rapporteurs link`
- `Com_op_i rapporteurs appt date`
- `Commission DG`
- `Commissioner`
- `Mandatory consultation of other institutions_i`
- `Mandatory consultation of other institutions_i_link`

#### Used later by

- `wide_meta`

---

### 04. Build wide meta table

#### Task name

`wide_meta`

#### Script

`scripts/create_wide_meta.py`

#### Function file

This is a script only file. No dependency on functions.

#### Depends on

- `scrape_cod_procedures`
- `meta_table`

#### Inputs

- `bld/oeil_cod_procedures.csv`
- `bld/meta_table.csv`
- `bld/meta_table.json`

#### Outputs

- `bld/wide_meta.csv`
- `bld/meta_council_info.csv`

#### Purpose

Converts the long `bld/meta_table.csv` into a wide format, with each of the `meta_column` row becoming a single column. The wide data now follows one row for one procedure. 

---

### 05. Build timeline table

#### Task name

`timeline_table`

#### Script

`scripts/create_timeline_table.py`

#### Function file

`functions/create_timeline_table.py`

#### Depends on

- `scrape_cod_procedures`

#### Inputs

- `bld/oeil_cod_procedures.csv`

#### Outputs

- `bld/timeline_table.csv`
- `bld/timeline_table.json`

#### Purpose

Builds the main procedural timeline table by combining:

- key events
- documentation gateway documents
- final act links where available

from `url` of each procedures in `bld/oeil_cod_procedures.csv`

Currently this step is also performed for the sample list of procedures. The output is a long table with one row corresponding to one event.

Output example:

| procedure | event_id | date | institution | event | reference | hyperlink | summary_available | summary_link |
|---|---:|---|---|---|---|---|---|---|
| 2021/0366(COD) | 1 | 17/11/2021 | European Commission | Legislative proposal published | COM(2021)0706 | `http://www.europarl.europa.eu/.../COM_COM(2021)0706_EN.pdf` | True | `https://oeil.europarl.europa.eu/oeil/en/document-summary?id=1683446` |
| 2021/0366(COD) | 2 | 17/11/2021 | European Commission | Legislative proposal | COM(2021)0706 | `http://www.europarl.europa.eu/.../COM_COM(2021)0706_EN.pdf` | True | `https://oeil.europarl.europa.eu/oeil/en/document-summary?id=1683446` |
| 2021/0366(COD) | 3 | 17/11/2021 | European Commission | Legislative proposal |  | `https://eur-lex.europa.eu/smartapi/cgi/sga_doc?...` | True | `https://oeil.europarl.europa.eu/oeil/en/document-summary?id=1683446` |

#### Used later by

- `com_vote_info`
- `com_vote_procedure`
- `com_roll_call`
- `other_format_com_vote_procedure`
- `scrape_council_lop_eulex_link`
- `scrape_voted_amendments_in_plenary`
- `scrape_all_amendments`
- `scrape_ep_final_vote_results`

---

### 06. Build transparency table

#### Task name

`transparency_table`

#### Script

`scripts/create_transparency_table.py`

#### Function file

`functions/create_transparency_table.py`

#### Depends on

- `scrape_cod_procedures`

#### Inputs

- `bld/oeil_cod_procedures.csv`

#### Outputs

- `bld/transparency_table.csv`
- `bld/transparency_table.json`


#### Purpose

Extracts transparency information from OEIL procedure pages, wherever they exist. The output is a long df with one row per member present.

Output example:

| procedure | name | member_link | role | committee_code | committee_name | committee_link | date | interest_representative |
|---|---|---|---|---|---|---|---|---|
| 2021/0366(COD) | BURKHARDT Delara | `https://www.europarl.europa.eu/meps/en/197440` | Shadow rapporteur | ENVI | Committee on the Environment, Public Health and Food Safety | `https://www.europarl.europa.eu/committes/en/ENVI` | 15/02/2023 | Together4Forests NGO coalition |
| 2021/0366(COD) | KARLSBRO Karin | `https://www.europarl.europa.eu/meps/en/197401` | Rapporteur | INTA | Committee on International Trade | `https://www.europarl.europa.eu/committes/en/INTA` | 03/02/2023 | Löfbergs lila |
| 2021/0366(COD) | TOUSSAINT Marie | `https://www.europarl.europa.eu/meps/en/97236` | Shadow rapporteur | ENVI | Committee on the Environment, Public Health and Food Safety | `https://www.europarl.europa.eu/committes/en/ENVI` | 30/11/2022 | Mighty Earth |

---

### 07. Build committee vote info

#### Task name

`com_vote_info`

#### Script

`scripts/create_com_vote_info.py`

#### Function file

`functions/create_com_vote_info.py`

#### Depends on

- `timeline_table`

#### Inputs

- `bld/timeline_table.csv`

#### Outputs

- `bld/committee_vote_info.csv`
- `bld/committee_vote_info.json`

#### Purpose

Finds committee report rows from the timeline table and extracts committee-level vote information from the linked report HTML.

This task identifies:

- lead committee rows
- opinion committee rows
- committees explicitly marked as not delivering opinions
- whether procedure tables are available
- whether roll-call tables are available
- raw HTML strings for procedure and roll-call sections

The output is a long df, with one row corresponding to one committee(lead/opinion).

Output Example:

| procedure | committee | designation | procedure_available | rollcall_available | procedure_string | rollcall_string |
|---|---|---|---|---|---|---|
| 2021/0366(COD) | ENVI | lead | True | True | `html_text` | `html_text` |


#### Used later by

- `com_vote_procedure`
- `com_roll_call`
- `other_format_com_vote_procedure`

---

### 08. Parse committee procedure tables

#### Task name

`com_vote_procedure`

#### Script

`scripts/create_com_vote_procedure.py`

#### Function file

`functions/create_com_vote_procedure.py`

#### Depends on

- `timeline_table`
- `com_vote_info`

#### Inputs

- `bld/timeline_table.csv`
- `bld/committee_vote_info.csv`

#### Outputs

- `bld/committee_vote_procedure_table.csv`
- `bld/committee_vote_procedure_table.json`

#### Purpose

Expands the raw `procedure_string` HTML from `committee_vote_info` into structured committee procedure fields.

The output is a long df, with one row corresponding to one head in the committee procedure table.

Output example:

Example output:

| procedure | committee | designation | head | value |
|---|---|---|---|---|
| 2021/0366(COD) | ENVI | lead | Title | Making available on the Union market as well as export from the Union of certain commodities and products associated with deforestation and forest degradation and repealing Regulation (EU) No 995/2010 |
| 2021/0366(COD) | ENVI | lead | References | COM(2021)0706 |
| 2021/0366(COD) | ENVI | lead | References | – C9-0430/2021 – |
| 2021/0366(COD) | ENVI | lead | References | 2021/0366(COD) |
| 2021/0366(COD) | ENVI | lead | Date submitted to Parliament | 18.11.2021 |
| 2021/0366(COD) | ENVI | lead | Committee responsible | ENVI |
| 2021/0366(COD) | ENVI | lead | Date announced in plenary | 17.1.2022 |
| 2021/0366(COD) | ENVI | lead | Committees asked for opinions | DEVE |
| 2021/0366(COD) | ENVI | lead | Rapporteurs | Christophe Hansen |
| 2021/0366(COD) | ENVI | lead | Date adopted | 12.7.2022 |
| 2021/0366(COD) | ENVI | lead | Result of final vote + | 60 |
| 2021/0366(COD) | ENVI | lead | Result of final vote – | 2 |
| 2021/0366(COD) | ENVI | lead | Result of final vote 0 | 13 |
| 2021/0366(COD) | ENVI | lead | Members present for the final vote | Maria Arena, Bartosz Arłukowicz, Simona Baldassarre, Traian Băsescu, Aurélia Beigneux, ... |
| 2021/0366(COD) | ENVI | lead | Substitutes present for the final vote | Matteo Adinolfi, Biljana Borzan, Milan Brglez, Asger Christensen, Rosanna Conte, ... |
| 2021/0366(COD) | ENVI | lead | Substitutes under Rule 209(7) present for the final vote | Isabella Adinolfi, Mazaly Aguilar, Vlad Gheorghe, Claude Gruffat, Krzysztof Hetman, ... |
| 2021/0366(COD) | AGRI | opinion | Title | Making available on the Union market as well as export from the Union of certain commodities and products associated with deforestation and forest degradation and repealing Regulation (EU) No 995/2010 |
| 2021/0366(COD) | AGRI | opinion | References | COM(2021)0706 |
| ... | ... | ... | ... | ... |

---

### 09. Expand committee roll-call tables

#### Task name

`com_roll_call`

#### Script

`scripts/create_com_roll_call.py`

#### Function file

`functions/create_com_roll_call.py`

#### Depends on

- `timeline_table`
- `com_vote_info`

#### Inputs

- `bld/timeline_table.csv`
- `bld/committee_vote_info.csv`

#### Outputs

- `bld/committee_roll_call_table.csv`
- `bld/committee_roll_call_table.json`

#### Purpose

Expands the raw `rollcall_string` HTML from `committee_vote_info` into structured committee roll-call vote tables. The output is a long df, with one row corresponding to one member who voted. The positive votes are recorded as pos. The negative votes are recorded as neg and the abstainances are recorded as abs.

Output example:

| procedure | committee | designation | vote_type | group | member |
|---|---|---|---|---|---|
| 2021/0366(COD) | ENVI | lead | pos | PPE | Isabella Adinolfi |
| 2021/0366(COD) | ENVI | lead | pos | PPE | Bartosz Arłukowicz |
| 2021/0366(COD) | ENVI | lead | pos | PPE | Traian Băsescu |
| 2021/0366(COD) | ENVI | lead | pos | PPE | Alexander Bernhuber |
| 2021/0366(COD) | ENVI | lead | pos | PPE | Nathalie Colin-Oesterlé |
| 2021/0366(COD) | ENVI | lead | pos | PPE | Salvatore De Meo |

---

### 10. Parse other-format committee vote procedures

#### Task name

`other_format_com_vote_procedure`

#### Script

`scripts/create_other_format_com_vote_procedure.py`

#### Function file

`functions/create_other_format_com_vote_procedure.py`

#### Depends on

- `timeline_table`
- `com_vote_info`
- `committee_dictionary`

#### Inputs

- `bld/timeline_table.csv`
- `bld/committee_vote_info.csv`
- `bld/committee_dictionary.csv`

#### Outputs

- `bld/committee_other_format_procedure_table.csv`
- `bld/committee_other_format_procedure_table.json`

#### Purpose

Handles committee vote procedure documents that are not available as normal HTML and need special parsing from other formats. Specifically, for older procedures, the committee procedure information is available in pdfs, instead of html. They could be available as a table in the pdf, or as a passage. This code handles both cases. The output is a long df with one row corresponding to one head in the procedure table. 

Output Example:

| procedure | committee | designation | head | value |
|---|---|---|---|---|
| 2000/0073(COD) | Committee on the Environment, Public Health and Consumer Policy | lead | Title | general product safety |
| 2000/0073(COD) | Committee on the Environment, Public Health and Consumer Policy | lead | References | COM (2000) 139 |
| 2000/0073(COD) | Committee on the Environment, Public Health and Consumer Policy | lead | References | C5-0224/2000 |

---

### 11. Scrape council votes and metadata

#### Task name

`scrape_council_votes_meta`

#### Script

`scripts/scrape_council_votes_meta.py`

#### Function file

`functions/scrape_council_votes_meta.py`

#### Outputs

- `bld/council_votes.csv`
- `bld/council_votes_meta.csv`
- `bld/council_votes.json`
- `bld/council_votes_meta.json`

#### Purpose

Scrapes Council vote data and associated metadata. This is done from `https://www.consilium.europa.eu/en/general-secretariat/corporate-policies/transparency/voting-results/`. This code extracts every single procedure available in this page. The output is a long df, with one row per document available in the page.

| doc_number | doc_link | procedure | date | meeting_number | council_configuration | policy_area | legislative_procedure | voting_rule | action_by_council | act_type | status | status_detail | title | votes_in_favour | votes_against | abstentions | not_participating | total_votes | countries_in_favour | countries_against | countries_abstentions | countries_not_participating | source_page | result_rank_on_page | search_url |
|---|---|---|---|---:|---|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|---|---|---:|---:|---|
| 16833/25 + ADD 1 + ADD 1 COR 1 | https://www.consilium.europa.eu/en/documents/... | 2023/0271(COD) | 21/04/2026 | 4168 | Foreign Affairs | Transport | Ordinary legislative procedure / Codecision | Qualified majority | Adoption of a Council's position (at first reading); ... | Regulation | Approved | Adoption of a Council's position (at first reading) | REGULATION OF THE EUROPEAN PARLIAMENT ... | 27 | 0 | 0 | 0 | 27 | AT\|BE\|BG\|CY\|CZ\|DE\|DK\|EE\|EL\|ES\|FI\|FR\|HR\|HU\|IE\|IT\|LT\|LU\|LV\|MT\|NL\|PL\|PT\|RO\|SE\|SI\|SK |  |  |  | 1 | 1 | https://www.consilium.europa.eu/en/general-secretariat/... |
| 17102/25 + ADD1 | https://www.consilium.europa.eu/en/documents/... | 2023/0228(COD) | 21/04/2026 | 4168 | Foreign Affairs | Agriculture | Ordinary legislative procedure / Codecision | Qualified majority | Adoption of a Council's position (at first reading); ... | Regulation | Approved | Adoption of a Council's position (at first reading) | REGULATION OF ... | 23 | 3 | 1 | 0 | 27 | BE\|BG\|CY\|CZ\|DK\|EE\|EL\|ES\|FI\|FR\|HR\|HU\|IE\|IT\|LT\|LU\|LV\|MT\|NL\|PL\|PT\|RO\|SE | AT\|DE\|SK | SI |  | 1 | 2 | https://www.consilium.europa.eu/en/general-secretariat/... |


Countries in favour, against and abstaining are mentioned with their 2 digit ISO codes. Total votes before Brexit: 28, total votes after brexit : 27. 

---

### 12. Scrape Council LOP EUR-Lex links

#### Task name

`scrape_council_lop_eulex_link`

#### Script

`scripts/create_council_lop_eulex_link.py`

#### Function file

This is a script-only task.

#### Depends on

- `timeline_table`

#### Inputs

- `bld/timeline_table.csv`

#### Outputs

- `bld/timeline_table_eulex_link_check.csv`

#### Purpose

This the first step in extracting the Council list of participants present during the final votes. It checks and verifies EUR-Lex accessibility and returns the links to the procedure pages in EU-Lex. 

For now, this is done for the sample list of procedures only. The output is a wide df, with one row per procedure.

Output example: 

| procedure | date | event | hyperlink | celex_number_raw | celex_number | eurlex_url | browser_status |
|---|---|---|---|---|---|---|---|
| 1994/0272(COD) | 18/09/1996 | Final act published in Official Journal | https://eur-lex.europa.eu/smartapi/cgi/...numdoc=31996L0057 | 31996L0057 | 31996L0057 | https://eur-lex.europa.eu/legal-content/EN/HIS/?uri=CELEX:31996L0057 | reachable |
| 2000/0073(COD) | 15/01/2002 | Final act published in Official Journal | https://eur-lex.europa.eu/smartapi/cgi/...numdoc=32001L0095 | 32001L0095 | 32001L0095 | https://eur-lex.europa.eu/legal-content/EN/HIS/?uri=CELEX:32001L0095 | reachable |
| 2007/0295(COD) | 18/07/2009 | Final act published in Official Journal | https://eur-lex.europa.eu/smartapi/cgi/...numdoc=32009R0595R(01) | 32009R0595R | 32009R0595 | https://eur-lex.europa.eu/legal-content/EN/HIS/?uri=CELEX:32009R0595 | reachable |


#### Used later by

- `scrape_council_lop_pres_con_links`

---

### 13. Extract Council PRES/CONSILIUM links

#### Task name

`scrape_council_lop_pres_con_links`

#### Script

`scripts/create_council_lop_pres_con_links.py`

#### Function file

This is a script only file. 

#### Depends on

- `scrape_council_lop_eulex_link`

#### Inputs

- `bld/timeline_table_eulex_link_check.csv`

#### Outputs

- `bld/pres_con_links.csv`

#### Purpose

Extracts Council PRES/CONSILIUM links from the EUR-Lex pages and checks whether linked pages and PDFs are accessible. The reason is because some of the list of participants are present in the PRES links from EUR-Lex. The newer ones are handled in the later steps. 
This is a wide df, with one row per procedure. 

Output Example:

| procedure | pres_link | document_found | pdf_link |
|---|---|---|---|
| 2000/0073(COD) | http://europa.eu/rapid/pressReleasesAction.do?...reference=PRES/01/35... | True | https://ec.europa.eu/commission/presscorner/api/files/document/print/en/pres_01_35/PRES_01_35_EN.pdf |
| 2010/0377(COD) | http://europa.eu/rapid/pressReleasesAction.do?...reference=PRES/12/283... | True | https://ec.europa.eu/commission/presscorner/api/files/document/print/en/pres_12_283/PRES_12_283_EN.pdf |
| 2010/0380(COD) | http://europa.eu/rapid/pressReleasesAction.do?...reference=PRES/12/185... | True | https://ec.europa.eu/commission/presscorner/api/files/document/print/en/pres_12_185/PRES_12_185_EN.pdf |

#### Used later by

- `scrape_council_lop_pres_con`

---

### 14. Extract Council PRES/CONSILIUM participants

#### Task name

`scrape_council_lop_pres_con`

#### Script

`scripts/create_council_lop_pres_con.py`

#### Function file

`functions/create_council_lop_pres_con.py`

#### Depends on

- `scrape_council_lop_pres_con_links`

#### Inputs

- `bld/pres_con_links.csv`

#### Outputs

- `bld/council_lop_pres_con.csv`
- `bld/council_lop_pres_con.json`

#### Purpose

Extracts Council participants from PRES/CONSILIUM PDFs. The output is a long df with one row per participant. 

Output example:

| procedure | group | participant | role |
|---|---|---|---|
| 2000/0073(COD) | Belgium | Mr Didier REYNDERS | Minister for Finance |
| 2000/0073(COD) | Denmark | Mr Poul Skytte CHRISTOFFERSEN | Ambassador, Permanent Representative |
| 2000/0073(COD) | Germany | Mr Caio KOCH-WESER | State Secretary, Federal Ministry of Finance |
| 2000/0073(COD) | Greece | Mr Yannos PAPANTONIOU | Minister for the National Economy and Finance |
| 2000/0073(COD) | Spain | Mr Rodrigo de RATO y FIGAREDO Second | Deputy Prime Minister and Minister for Economic Affairs |
| 2000/0073(COD) | France | Mr Laurent FABIUS | Minister for Economic Affairs, Finance and Industry |

---

### 15. Extract Council meeting document participants

#### Task key

`scrape_council_lop_meeting-docs`

#### Internal task name

`scrape_council_lop_meeting_docs`

#### Script

`scripts/create_council_lop_meeting_doc.py`

#### Function file

`functions/create_council_lop_meeting_doc.py`

#### Outputs

- `bld/council_lop_out_docs.csv`

#### Purpose

Extracts Council participants from Council meeting-document PDFs. This step is performed for all the meetings existing in `https://www.consilium.europa.eu/en/meetings/calendar/`. All the procedures having a pdf for the list of participants in their meeting page have been extracted. The output df is a long df with one row per participant.

Output Example:

| procedure | group | participant | role |
|---|---|---|---|
| 2025/0051(COD) | Belgium | Mr Peter MOORS | Permanent Representative |
| 2025/0051(COD) | Bulgaria | Ms Elena SHEKERLETOVA | Deputy Minister for Foreign Affairs |
| 2025/0051(COD) | Czechia | Mr Martin DVOŘÁK | Minister for European Affairs |
| 2025/0051(COD) | Denmark | Ms Marie BJERRE | Minister for European Affairs |
---

### 16. Scrape voted amendments in plenary

#### Task name

`scrape_voted_amendments_in_plenary`

#### Script

`scripts/create_voted_amendments.py`

#### Function file

`functions/create_voted_amendments.py`

#### Depends on

- `timeline_table`

#### Inputs

- `bld/timeline_table.csv`

#### Outputs

- `bld/voted_amendments_all.csv`
- `bld/failed_voted_amendments.csv`

#### Purpose

Scrapes amendments voted in plenary from amendment PDFs in the plenary page and saves extracted amendment data. The output is a long df with one row corresponding to one amendment.  Currently this is performed only for the sample list of procedures. 

Output example:

| procedure | amendment_number | ref_text | left_header | right_header | text_proposed_by_commission | amended_prose | source_index | source_am_no | source_pdf_link |
|---|---:|---|---|---|---|---|---:|---|---|
| 2021/0366(COD) | 1 | Proposal for a regulation Recital 1 | Text proposed by the Commission | Amendment | (1) Forests provide a broad variety of environmental, economic and social benefits, including timber and non-wood forest products and environmental services essential... | (1) Forests provide a broad variety of environmental, economic and social benefits, including timber and non-wood forest products and environmental services essential... | 0 | 001-239 | https://www.europarl.europa.eu/.../A-9-2022-0219-AM-001-239_EN.pdf |
| 2021/0366(COD) | 2 | Proposal for a regulation Recital 2 | Text proposed by the Commission | Amendment | (2) Deforestation and forest degradation are taking place at an alarming rate. The Food and Agriculture Organization of the United Nations estimates that... | (2) Deforestation, forest degradation and forest conversion are taking place at an alarming rate. The Food and Agriculture Organization of the United Nations... | 0 | 001-239 | https://www.europarl.europa.eu/.../A-9-2022-0219-AM-001-239_EN.pdf |
| 2021/0366(COD) | 3 | Proposal for a regulation Recital 3 | Text proposed by the Commission | Amendment | (3) Deforestation and forest degradation contribute to the global climate crisis in multiple ways. Most importantly, they increase greenhouse gas emissions through associated... | (3) Deforestation, forest degradation and forest conversion contribute to the global climate crisis in multiple ways. Most importantly, they increase greenhouse gas emissions... | 0 | 001-239 | https://www.europarl.europa.eu/.../A-9-2022-0219-AM-001-239_EN.pdf |

It also records the failed procedures, for which this could not be extracted, in the following table:

| index | procedure | am_no | hyperlink | error |
|---:|---|---|---|---|
| 15 | 2010/0380(COD) | 001-025 | https://www.europarl.europa.eu/.../A-7-2012-0043-AM-001-025_EN.pdf | No amendments extracted |
| 44 | 2020/0262(COD) | 075-075/REV1 | https://www.europarl.europa.eu/.../A-9-2021-0114-AM-075-075_EN.pdf | No amendments extracted |

where the index is the row index in the `timeline_table.csv`.  The reason these are failing is because they follow a different pattern of amendments. They do not follow the standard tabular format of the text proposed by commission on the left, and the amendment on the right. Instead, everything is noted as a passage.

---

### 17. Scrape all proposed amendments

#### Task name

`scrape_all_amendments`

#### Script

`scripts/create_all_amendments.py`

#### Function file

`functions/create_all_amendments.py`

#### Depends on

- `timeline_table`

#### Inputs

- `bld/timeline_table.csv`

#### Outputs

- `bld/proposed_amendments_all.csv`
- `bld/all_amendments_document_links.csv`
- `bld/failed_all_amendments_pdf_text.csv`
- `bld/failed_all_amendments_parsing.csv`

#### Purpose

This task scrapes all proposed amendments from committee draft reports and committee amendment PDFs. First it creates a reference link data `bld/all_amendments_document_links.csv` and then uses that to extract a long df, with one row per amendment `bld/proposed_amendments_all.csv`. Currently it is done for the sample list of procedures.

Output example:

| procedure | event | reference | link | amendment_number | authors | ref_text | left_header | right_header | text_proposed_by_commission | amended_text | justification | origin | source_page_start | source_page_end |
|---|---|---|---|---:|---|---|---|---|---|---|---|---|---:|---:|
| 2007/0295(COD) | Amendments tabled in committee | PE407.814 | https://www.europarl.europa.eu/.../ENVI-AM-407814_EN.pdf | 17 | Anja Weisgerber, Holger Krahmer | Proposal for a regulation \| Recital 5 | Text proposed by the Commission | Amendment | (5) Achieving EU air quality objectives requires a continuing effort to reduce vehicle emissions... | (5) Achieving EU air quality objectives requires a continuing effort to reduce vehicle emissions... | Parliament and the Commission seek to improve air quality in the EU... | Or. de | 3 | 3 |
| 2007/0295(COD) | Amendments tabled in committee | PE407.814 | https://www.europarl.europa.eu/.../ENVI-AM-407814_EN.pdf | 18 | Anja Weisgerber | Proposal for a regulation \| Recital 8 a (new) | Text proposed by the Commission | Amendment |  | (8a) It is essential to develop a European standard format for on-board diagnostic... | See justification for the amendment to Article 6(1). | Or. de | 4 | 4 |
| 2007/0295(COD) | Amendments tabled in committee | PE407.814 | https://www.europarl.europa.eu/.../ENVI-AM-407814_EN.pdf | 19 | Anja Weisgerber, Holger Krahmer | Proposal for a regulation \| Article 5 - paragraph 4 - subparagraph 2 | Text proposed by the Commission | Amendment | The Commission may, in accordance with the procedure referred to in Article 39(9)... | deleted | This paragraph is formulated too indeterminately and too openly and allows the Commission too much freedom of action... | Or. de | 5 | 5 |


The failed extractions are also noted in `bld/failed_all_amendments_pdf_text.csv` and `bld/failed_all_amendments_parsing.csv`

| procedure | event | reference | link | error |
|---|---|---|---|---|
| 2014/0091(COD) | Committee draft report | PE536.213 | https://www.europarl.europa.eu/.../JURI-CM-536213_EN.pdf | No amendments extracted from PDF |
| 2018/0298(COD) | Committee draft report | PE629.544 | https://www.europarl.europa.eu/.../TRAN-PR-629544_EN.pdf | No amendments extracted from PDF |
|

---

### 18. Scrape European Parliament final vote results

#### Task name

`scrape_ep_final_vote_results`

#### Script

`scripts/create_ep_final_vote_results.py`

#### Function file

`functions/create_ep_final_vote_results.py`

#### Depends on

- `timeline_table`

#### Inputs

- `bld/timeline_table.csv`

#### Outputs

- `bld/final_vote_ep_extracted.csv`
- `bld/failed_ep_vote_extractions.csv`


#### Purpose

Scrapes final vote results in the European Parliament and saves extracted vote tables. Currently it is done for the sample list of procedures. The output df is a long df with one row corresponding to one row in the vote table in OEIL. The additional_remarks column notes the passage of notes below each table. It is repeated for every row in the table currently. 

Output example:

| procedure | event_id | Subject | Am No | Author | RCV etc. | Vote | RCV/EV – remarks | additional remarks |
|---|---:|---|---|---|---|---|---|---|
| 2021/0366(COD) | 30 | Amendments by the committee responsible – put to the vote collectively |  | committee |  | + |  | Requests for roll-call votes: PPE: amendments 40, 87, 105, 127, 130, 148, 149, 158. Requests for separate votes: ECR: amendments 19, 25, 40, 43, 53, 80, 83, 84, 87, 89, 92, 99, 100, 105, 106, 109, 110, 129, 130, 138, 145, 148, 149, 150, 166, 178, 186, 192, 227, 233, 237... |

The failures are noted in `bld/failed_ep_vote_extractions.csv`:

| df1_index | procedure | event_id | hyperlink | error |
|---:|---|---:|---|---|
| 133 | 2010/0380(COD) | 17 | https://www.europarl.europa.eu/doceo/document/PV-7-2012-04-18-VOT_EN.html?item=1 | Could not identify the main vote table. |
| 317 | 2011/0465(COD) | 22 | https://www.europarl.europa.eu/doceo/document/PV-7-2014-03-11-VOT_EN.html?item=9 | Could not find report reference A7-0273/2012 on the page. |

where `df1_index` is the row index in `timeline_table.csv`. 

---

## NOTES

- To make the scrapper run for the full list of procedures, do the following:
    - Change from `procedures` list to all the unique `procedure`s in the `oeil_cod_procedures.csv` table in `scripts/create_meta_table.py` and in `scripts/create_timeline_table.py`. As a result, every subsequent script which uses `bld/timeline_table.csv` as a dependency will be altered to run for every single policy. 

- Procedures before 2014 do not have council votes or council meeting data available in the website.



