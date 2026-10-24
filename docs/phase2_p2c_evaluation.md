# P2c independent evaluation: workflow (prepared; NOT run; data not approved)

**Status:**
- The workflow is implemented and tested on synthetic files only.
- **No evaluation data has been downloaded or processed**, and FLORES+ access terms have **not** been accepted.
- **The success criterion has not been evaluated.**

## Two kinds of measurement
| | Controlled-data demo | Independent evaluation (this document) |
|---|---|---|
| Data | `phase1-kn-hi-v1`, `phase1-en-mixed-v1`: small, synthetic/curated, for harness validation | an approved, independent dataset. Candidate: FLORES+ `devtest` for Hindi, Kannada and English |
| Script | `benchmarks/phase2/p2c_demo.py` (`docs/phase2_p2c_demo.md`) | `benchmarks/phase2/evaluate_p2c.py` |
| Can decide the criterion? | **no** | **yes**, once approved and run |
| Results so far | P2c 9,061 B against best `sgtt` 12,300 B over 40 controlled columns (not evidence) | **none** |

## Pre-registered criterion (unchanged; pinned in the code, not configurable)
From `docs/phase2_proposal.md` §7. P2c succeeds only if **all** of these hold:
1. every value round-trips exactly;
2. P2c stores **at least 5% fewer total bytes** than the per-column best `sgtt` baseline (the smaller of OpenAI200K Dense and Gemma3 Dense) **for Hindi and for Kannada**;
3. **no evaluated group** (Hindi, Kannada, English) is more than 5% worse.

Medians, P2b and timings are reported but don't decide the outcome. The vocabulary (`1e12dc48…`, L = 32,768) is frozen. It is **never** retrained, and L is never re-chosen from evaluation results.

## What the workflow does
1. **Reads the spec.** `datasets/external_manifests/flores_plus_devtest_e707e62e.json` (committed). It refuses unless:
   - the owner's approvals are all `true`, with a name and a date;
   - the decontamination decision is made;
   - the files cover Hindi and Kannada (English is allowed as a regression group);
   - every file has its official size and Git blob SHA-1.
2. **Checks the storage root,** which must be the approved one, outside every Git repository (`/Users/Shared/hashcode-data/flores_plus/4.6/`). It refuses any `*.partial` file.
3. **Verifies each file before use:** size and Git blob SHA-1 against the official values; valid UTF-8 JSONL; the stated text and ID fields; no duplicate IDs; the expected record count.
4. **Pins the vocabulary.** The frozen P2c vocabulary SHA-256 is hard-coded, and the P2a/P2b vocabulary SHA-256 is checked too.
5. **Converts** to the shared sample schema in `<storage_root>/runs/<stamp>/`:
   - records stay in file order;
   - each gets the ID `<group>-<id>`;
   - **text is unchanged** (no normalization);
   - columns are 64 consecutive sentences per group (`col-<group>-NNN`, non-overlapping).
6. **Decontamination check**, if the decision is `report-only`. It looks for exact matches of each evaluation sentence, and each line of 32 bytes or more, in the frozen Wikipedia training files (SHA-checked against the vocabulary manifest). It reports counts only. The vocabulary is **not** changed.
7. **Runs the existing benchmark twice** (`run_column_benchmark.py --external-dataset`, outside the repository). It requires 0 differences between the runs, and the existing auditor must report 0 problems on both.
8. **Aggregates** per group: raw, best `sgtt`, P2b and P2c total stored bytes (the harness's own accounting); exact round trips; and the criterion decision.
9. **Publishes aggregates only** to `results/phase2/p2c-eval-<name>-<split>-<stamp>/`: `summary.json`, `summary.txt`, `groups.csv`, `per_column.csv`.
   - First, a guard scans these files for any evaluation sentence of 12 bytes or more, its hex or JSON encoding, or any Devanagari/Kannada text run. If anything is found, **nothing is published** (exit 18).
   - Samples, containers and decoded values stay under the storage root.

**Exit codes:** 0 OK; 2 usage; 10 missing or partial file; 11 checksum mismatch; 12 incomplete or malformed data; 13 not approved or invalid spec; 14 overlap check; 15 vocabulary mismatch; 16 benchmark failed or runs differ; 17 audit; 18 text guard.

## Official file metadata (public listing, read 2026-10-25; the gate was not accepted)
From `https://huggingface.co/api/datasets/openlanguagedata/flores_plus/tree/e707e62e762a9e2faca3933aa315f4665cc3cd8f/devtest`:

| Group | File | Size (bytes) | Git blob SHA-1 |
|---|---|---|---|
| hi | `devtest/hin_Deva.jsonl` | 644,787 | `8fe2f4435a5854f691279e1affd085ca4c3f0a37` |
| kn | `devtest/kan_Knda.jsonl` | 683,237 | `17183ea16d4bcd5da43f3fc0bd910fa4aef40642` |
| en | `devtest/eng_Latn.jsonl` | 439,951 | `0e94992350ebcf14fd775a762d36df5e5f9f6b71` |

**Not yet confirmed (they are behind the gate):**
- the "4.6" version label of revision `e707e62e…`;
- the JSONL field names (the spec assumes `text` and `id`);
- the record count (the spec assumes 1,012 per file, the usual FLORES `devtest` size).

The workflow **fails safely** if any of these is wrong (exit 12). Correct the spec and record why.

## Approvals pending (owner only; none is granted)
1. **Accept the access gate yourself** on https://huggingface.co/datasets/openlanguagedata/flores_plus, while logged in to your own account. Claude does not accept terms.
2. **Approve evaluation-only use** of `devtest` for `hin_Deva`, `kan_Knda` and `eng_Latn`. It is never used for training or for choosing L.
3. **Approve the storage location** `/Users/Shared/hashcode-data/flores_plus/4.6/`, outside every Git repository.
4. **Approve aggregate-only publication:** no evaluation text, samples or containers in the repository.
5. **Decide on decontamination:**
   - **`report-only` (suggested):** check the evaluation sentences against the frozen training text, and report the overlap as a limitation.
   - **`declined`:** record the missing check as a limitation.

   Filtering the training corpus before the build, as in the original plan §4.1, is no longer possible without rebuilding the frozen vocabulary.
6. **Approve the download** of the three files above (about 1.7 MB) at the pinned revision.

## Commands, after the approvals
```bash
# 1. Owner: accept the gate in the browser, then create a read token (huggingface.co/settings/tokens) and export it locally.
export HF_TOKEN=...            # never commit it
R=e707e62e762a9e2faca3933aa315f4665cc3cd8f; D=/Users/Shared/hashcode-data/flores_plus/4.6
for f in hin_Deva kan_Knda eng_Latn; do
  mkdir -p $D/devtest && curl -fL -H "Authorization: Bearer $HF_TOKEN" -o $D/devtest/$f.jsonl.partial \
    "https://huggingface.co/datasets/openlanguagedata/flores_plus/resolve/$R/devtest/$f.jsonl" && mv $D/devtest/$f.jsonl.partial $D/devtest/$f.jsonl
done
# 2. Owner: in the spec, set the four approvals to true, approved_by/approved_on, and decontamination ("report-only" or "declined").
# 3. Evaluate (verifies everything first; publishes aggregates only):
python3 -I benchmarks/phase2/evaluate_p2c.py --spec datasets/external_manifests/flores_plus_devtest_e707e62e.json
```
**Prerequisites:**
- the harness is built (`cmake --build external/token-vldb2026/build-arm64 --target phase1_column_harness`);
- Python ≥ 3.14;
- for `report-only`, the frozen training files in `/Users/Shared/hashcode-data/wikipedia/20261001/train/`.

## Tests (synthetic only)
`python3 -I tests/p2c/test_evaluate_p2c.py`, 8 tests:
- **Happy path, run twice:** identical aggregates; no sentence, hex or Indic text published; text-bearing artifacts only under the storage root; no overwriting.
- **Report-only overlap:** a sentence planted in the training text is found.
- **Text guard:** trips on plain text, hex and Indic runs.
- **Failure exit codes:** missing file and partial file (10); checksum mismatch (11, with nothing processed); wrong count, missing field and duplicate ID (12); vocabulary mismatch (15).
- **Approval and spec guards:** the real unapproved spec is refused (13) even with `--synthetic-test`; a synthetic spec is refused in real mode; a pending decontamination decision and a missing Kannada file are refused; a storage root inside the repository is refused (2).
- **Pinned criterion:** checked on hand-built aggregates, including the exact 5% boundaries.
