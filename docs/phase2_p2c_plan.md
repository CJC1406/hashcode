# Phase 2, experiment 3: P2c plan (data review and design; nothing implemented)

**Update (2026-10-24): design decisions resolved.**
- The builder is implemented and tested on a synthetic fixture only (`docs/phase2_p2c_report.md`).
- Its open design decisions were resolved **before any real data was touched**. The full record is in `docs/phase2_p2c_report.md` §3.
- Where a resolution changes this plan, the change is marked **Resolved** below. The original wording is kept, struck through or quoted.
- The real-data success criterion (§4.6, `docs/phase2_proposal.md` §7) is **unchanged** and still blocked on D3.

**Status:** a plan for the project owner's approval.
- Nothing has been downloaded, no gated content was accessed, and no corpus has been extracted, tokenized or trained on.
- No vocabulary has been built.
- The licence findings below were read on 2026-10-24 from the official pages cited in §7. They are **not legal advice**. Anything a page doesn't state explicitly is marked *unresolved*.

## 1. Where things stand
- **Frozen baselines:**
  - raw HCC1;
  - `sgtt` OpenAI200K and Gemma3, Dense (upstream `e202e36` plus the build patch);
  - P1 (`8c85586c…`), P2a (`c99ff52f…`), and **P2b**: HCC1 codec 3 with the P2a vocabulary (`docs/phase2_p2b_report.md`).
- **Checksums verified on 2026-10-24:** `kn_hi_v1` `359269f4…`, `en_mixed_v1` `6c4685c2…`, P1 and P2a vocabularies.
- **Why P2c:** on the controlled data, P2b is 8.4% larger than the best `sgtt` baseline (13,331 vs 12,300 bytes). The gap is almost entirely token count on long Hindi and Kannada text: P2b needs 1.6–2.0× as many tokens as `sgtt` there.
- **P2c hypothesis (H3):** adding multi-akshara and word entries learned from an **approved training corpus** brings Indic bytes per token close to `sgtt`, and closes the byte-weighted gap.
- **Owner decisions already recorded:**
  - FLORES+ is a conditional candidate for **evaluation only**.
  - Kannada–English code-mixed evaluation is **excluded** from the initial P2c criterion (future work, §6).
  - No unapproved data may be used.

## 2. Training-source candidates
**Update (2026-10-24):** a second, read-only review of Sangraha, Wikipedia (`hiwiki`/`knwiki`, dump 20261001) and IndicCorp v2 is in `docs/phase2_p2c_report.md` §9. It adds sizes, formats, citations and the open questions. The approval checklist is in that report's §8. The table below is kept as first written.

| Candidate | Official source; version or date | Languages and scripts | Size and content (as documented) | Licence and access (as stated) | Third-party material | Commercial use | Extracting a vocabulary; redistributing derived tokens | Attribution | Retain locally; redistribute derivatives | Open questions; contact |
|---|---|---|---|---|---|---|---|---|---|---|
| **IIT Bombay Hindi monolingual corpus** (with the EN–HI parallel corpus) | cfilt.iitb.ac.in/iitb_parallel; parallel v3.1 (Dec 2021); the monolingual release date isn't given | Hindi (Devanagari); the parallel corpus adds English | 45,124,642 sentences: HindMonoCorp 44,486,496, plus BBC, Wikipedia, judicial, health, tourism. Parallel: 1,659,082 segments. The **Hindi side was normalized to canonical Unicode** (Indic NLP Library) | "Creative Commons Attribution-**NonCommercial** 4.0". Download links; no gate stated | "The corpora we compiled from other sources are available under their **respective licenses**": HindMonoCorp, BBC, Wikipedia and others have their own terms, **not reviewed here** | **Non-commercial only** (CC BY-NC 4.0) | **Unresolved.** NC permits non-commercial adaptation, but each sub-corpus's terms apply, and whether a token list is an adaptation isn't addressed | Cite Kunchukuttan, Mehta & Bhattacharyya, LREC 2018 | **Unresolved** for sub-corpora. Under NC, any redistributed derivative would also have to stay non-commercial | Is ByteME/Hashcode non-commercial? What are the HindMonoCorp terms? Normalization means the frequencies reflect normalized text. Contact: pb@cse.iitb.ac.in, anoop.kunchukuttan@gmail.com |
| **LDC-IL "A Gold Standard Kannada Raw Text Corpus"** (CIIL Mysore; the result found for the ILCI search; it isn't confirmed to be the ILCI monolingual set) | data.ldcil.org/a-gold-standard-kannada-raw-text-corpus; released 04-Apr-2019; SKU LDCIL-184, ISBN 978-81-7343-226-2 | Kannada | 7,763,124 words and 64,909,781 characters across 1,772 titles: book extracts keyed in by hand plus crawled news. The domain table on the page is internally inconsistent | Terms field: "General instructions for use of the resources provided by LDC-IL". There are separate **Commercial** and **Non-Commercial User Undertaking** documents, **not reviewed** | Book and news extracts: the rights in the source texts aren't stated | Governed by the undertakings: **unresolved** | **Unresolved** | Cite Ramamoorthy et al. 2019, and Choudhary & Ramamoorthy 2019 | **Unresolved**: needs the undertaking text | Read both undertakings. Is this the ILCI Kannada monolingual corpus? Price and access? Contact: via data.ldcil.org (CIIL); no address on the page |
| **AI4Bharat Sangraha** | huggingface.co/datasets/ai4bharat/sangraha; no version or date on the card (the paper is dated 2024-03-11) | 22–23 languages, including `hin_Deva`, `kan_Knda` and English | Subsets: **verified** (curated websites, OCR of PDFs, transcribed media), unverified (filtered existing corpora), and synthetic (machine-translated English Wikimedia text, and romanized text). Kannada verified ≈1,778M tokens; Hindi verified ≈12,617M; 705 GB in total | Card metadata: "cc-by-4.0". **No licence text and no gate** on the card | **Not addressed.** There's no statement about copyright in the crawled, OCR'd or transcribed sources, and no takedown process | CC BY 4.0 would allow it, *if* the label covers the content: **unresolved** | **Unresolved**, for the same reason | Cite IndicLLMSuite (Khan et al., arXiv:2403.06350) | Would be permitted under CC BY *if* the label applies: **unresolved** | Does CC BY 4.0 cover the underlying source text? The synthetic subset derives from Wikimedia, so it could overlap FLORES's source domains; avoid it. Contact: AI4Bharat (through the Hugging Face org or GitHub) |
| **AI4Bharat IndicCorp v2** | huggingface.co/datasets/ai4bharat/IndicCorpV2 (reviewed earlier in Phase 1) | 23 Indic splits, including `hin_Deva` (≈152M rows) and `kan_Knda` (≈48.7M rows); no English | Web-crawled monolingual text, ≈275 GB in total | The card says the datasets are released under **CC0** | **Not addressed:** crawl sources aren't named, and the copyright of the crawled text isn't discussed | CC0 *if* it applies: **unresolved** | **Unresolved** | Cite the IndicBERT/IndicCorp paper (ACL 2023) | **Unresolved** | The same crawl-copyright question as Sangraha. Contact: AI4Bharat |
| **Wikipedia dumps, Hindi and Kannada** (`hiwiki`, `knwiki`) | dumps.wikimedia.org; a dated dump is chosen at download time | Hindi, Kannada (plus other scripts inside articles) | Encyclopedic articles. Sizes not checked here | Original text is under **GFDL** (the linked page is v1.3) **and CC BY-SA 4.0**. "Some text may be available only under the Creative Commons license". The Terms of Use control | Dumps "may contain" unremoved infringements, used "AT YOUR OWN RISK". Fair-use material may not be reusable elsewhere | Allowed under BY-SA, with share-alike | **Unresolved:** whether a frequency-ranked list of short substrings is "adapted material" that falls under share-alike. If it is, the published vocabulary would have to be CC BY-SA 4.0 with attribution | Required under BY-SA and GFDL (Terms of Use §7; not quoted on the dumps page) | Retaining is fine; derivatives are BY-SA if they count as adaptations | Accept BY-SA for the vocabulary file, or get advice. Also: FLORES+ comes from Wikinews, Wikijunior and Wikivoyage, which are separate projects from Wikipedia, but decontamination (§4.1) is still required. Contact: Wikimedia legal (Terms of Use) |
| **Leipzig Corpora Collection** (Hindi, Kannada) | wortschatz.uni-leipzig.de | probably Hindi and Kannada news/web/Wikipedia | **Not verified:** the download page was behind a bot check and couldn't be read | **Not verified** | not verified | not verified | not verified | not verified | not verified | Re-check manually before considering it |

### Recommendation (not a selection)
- **No candidate is cleared for use.** Each has at least one unresolved point about whether we may extract a vocabulary and **publish the derived token list** in this public repository (`CJC1406/hashcode`).
- **Clearest written licence: Wikipedia (`hiwiki`, `knwiki`).** I suggest reviewing it first. It covers both languages, the licence text is explicit (CC BY-SA 4.0 + GFDL), and the data can be kept locally.
  - **What the owner must accept:** the published P2c vocabulary file would most likely be released under CC BY-SA 4.0, with attribution to Wikipedia contributors and a pinned dump date, *if* a token list counts as an adaptation.
  - **Mitigation:** keep the vocabulary file under a separate licence note (`codec/p2c/LICENSE-vocabulary.md`).
- **Alternatives, pending clarification from the providers:**
  - **Sangraha "verified" subset** (CC BY 4.0 label): would need confirmation that the label covers the underlying text.
  - **IITB Hindi monolingual corpus:** acceptable **only if** the project is non-commercial and the sub-corpus licences (especially HindMonoCorp) are confirmed. It is also normalized and Hindi-only.
  - **LDC-IL Kannada:** needs the undertakings to be read.

## 3. FLORES+ approval checklist (evaluation only)
**Update (2026-10-25):** the evaluation workflow is prepared and tested on synthetic data (`docs/phase2_p2c_evaluation.md`). The approvals below are still pending.

| Item | Documented (dataset card, read 2026-10-24) | Status |
|---|---|---|
| Licence and version | CC BY-SA 4.0; "The current version of the dataset is **4.6**" | to be confirmed at access time (§5) |
| Evaluation only | "It should not be used as training data." | P2c never trains on it or builds a vocabulary from it. Its only other use is the decontamination filter in §4.1 |
| Gate | "you have to accept the conditions to access its files and content"; "Accept the terms of use… on this page" | **the owner must accept the gate personally.** Not done here |
| Redistribution | "please do not redistribute this file publicly, unless you protect it from automatic scrapping!" | No FLORES+ text, hex, containers or decoded values may be committed or pushed (§5) |
| Attribution | "please cite the relevant papers listed in `bibliography.bib`": the original FLORES papers (e.g. arXiv 2207.04672) and the FLORES+ shared-task papers | cite them in the P2c report |
| Splits | dev 997 and devtest 1,012 sentences per language; `eng_Latn`, `hin_Deva` and `kan_Knda` are listed | the split to use is proposed in §4.6 |
| Local storage | not specified by the card | **Proposed:** `/Users/Shared/hashcode-data/flores_plus/4.6/`. It must be outside `/Users/cjc`, **which is itself a Git working tree**, and outside `/Users/cjc/Downloads/hashcode`. Only the owner should be able to read it |
| Recording the version without committing content | — | **Proposed:** commit only `datasets/external_manifests/flores_plus_4.6.json`, with the Hugging Face repo revision (commit hash), file names, byte sizes and SHA-256s. Never the text |

## 4. P2c design (to be frozen before any evaluation)

### 4.1 Data separation
- **Training corpus:** the approved source (§2), pinned by version or dump date. Its manifest of file names, sizes and SHA-256s is committed; the text never is. It is stored outside Git, next to FLORES+, in `/Users/Shared/hashcode-data/<source>/<version>/`.
- **Deterministic split of the training corpus:**
  - `train` is 95% and `heldout` is 5%, assigned per document by `SHA-256(document id) mod 20 == 0` → `heldout`.
  - `heldout` is used **only** to choose vocabulary parameters (§4.4).
- **Decontamination against FLORES+:**
  - Drop any training *document* containing a 32-byte sequence that also occurs in FLORES+ dev or devtest for the same language.
  - This uses FLORES+ only as a filter. It is matched through a SHA-256 set of 32-byte windows held in memory, and no FLORES+ text is written into the vocabulary or committed. Record the number of documents dropped.
  - **Owner confirmation needed:** that this filtering use is compatible with "should not be used as training data". If not, skip decontamination and record that as a limitation.
- **The controlled datasets** (`kn_hi_v1`, `en_mixed_v1`) are used only for smoke and correctness tests, never as evidence.

### 4.2 Candidate extraction (training text only; no normalization; bytes as stored)
1. Read each document as UTF-8 bytes and skip invalid sequences when *counting*. The codec still handles any bytes through fallback.
2. **Segment** each line into maximal runs of characters from one script: Devanagari U+0900–097F or Kannada U+0C80–0CFF. ZWJ/ZWNJ (U+200D/U+200C) count as part of the run. A single preceding ASCII space is kept with the run.
3. **Split each run into aksharas** using the P1/P2a structural rules: consonant (+nukta)(+virama consonant)* (+dependent signs)*; or an independent vowel (+signs); or any other block code point on its own.
4. **Candidates** are every sequence of ~~2 to 8~~ consecutive aksharas within a run, with and without its leading space, of **at most 16 bytes** (the codec limit). Whole words are the case where the sequence covers the entire run.
   - **Resolved (report §3, D5, D6):** candidates are **1 or more** aksharas, bounded **only by 16 bytes**.
     - Single aksharas count only if P2a needs at least 2 tokens for them, for example conjuncts; the score in §4.3 already excludes the rest.
     - The 8-akshara bound is removed because it never applied: Devanagari and Kannada code points are 3 bytes each, so 16 bytes is at most 5 code points.
5. **Count** the occurrences of each candidate in `train`.

### 4.3 Ranking (deterministic)
- **Score:** `count × (p2a_tokens(candidate) − 1)`, where `p2a_tokens` is how many tokens the frozen P2a vocabulary needs for the candidate. This is the number of tokens the entry would save each time it's used.
- **Ties:** by byte length (longer first), then by raw bytes (ascending).
- **Selection:** pick greedily in score order, skipping candidates already in P2a. Scores are **not** recomputed after each pick, to keep the procedure simple and reproducible. The greedy-interaction approximation is recorded as a limitation.
- **Resolved (report §3, D3):** unchanged. Every occurrence counts, including overlapping ones, and there is no re-scoring. A re-scoring builder would be a separate variant.

### 4.4 Vocabulary layout, size and ID representation
- **Fixed at 65,536 entries,** so global IDs stay `u16` and the P2b codec (HCC1 codec 3) is reused **unchanged**. The only difference is the vocabulary file and its table ID.
- **Layout:** IDs 0–5,247 are the P2a core, unchanged: single bytes, akshara entries and space+akshara entries. Then come `L` learned entries, split **50/50 between Hindi and Kannada** (fixed in advance). The rest are P2a's ASCII entries in o200k rank order, truncated.
- **Choosing `L` (frozen before FLORES+):** try `L ∈ {4,096, 8,192, 16,384, 32,768}`. Pick the `L` with the smallest total of P2b-encoded bytes over `heldout`, which is split into 64-line columns in document order. Ties go to the smaller `L`. FLORES+ is **never** used to choose `L`.
- **Resolved (report §3, D1, D2, D7, D8):**
  - **Quotas:** an `L` is **eligible only if both Hindi and Kannada fill their L/2 quota.** Quotas never move between languages, so a selected or frozen vocabulary has no unfilled slot. If no candidate `L` is eligible, the build fails.
  - **Language of a held-out document:** the script with more code points. Columns are built **per language**: that language's held-out lines, in document order, 64 per column.
  - **Objective:** instead of the plain total, minimise the **mean over Hindi and Kannada of (held-out bytes with `L`) / (held-out bytes with the P2a vocabulary, i.e. P2b)**, in exact fractions, so each language counts equally whatever its share of the corpus. Ties still go to the smaller `L`.
  - **Freezing:** `--freeze` refuses a fixed `L` and refuses `--allow-unfilled`. `--allow-unfilled` is a test-only switch that returns unfilled slots to ASCII.
- **Freezing:** after choosing `L`, write the vocabulary, manifest and SHA-256, and commit them **before** any FLORES+ run. The commit hash is recorded in the evaluation report.

### 4.5 Byte fallback, reconstruction and accounting
- IDs 0–255 remain the single bytes, so every byte sequence can be encoded. Reconstruction is byte-exact by construction and verified per value.
- **Stored bytes per column:** HCC1 header + boundary table + P2b width byte + mapping + token IDs + 13-byte footer. The existing harness and auditor already check that these add up.
- **Vocabulary:** reported separately as a shared static asset, using the same rule as the baselines. Add a break-even analysis, and a **licence note** for the vocabulary file (§2).
- Also report fallback rate, bytes per token, setup time and encoding speed.

### 4.6 Evaluation protocol (needs the FLORES+ approval)
- **Data:** FLORES+ 4.6 **devtest** for `hin_Deva`, `kan_Knda` and `eng_Latn`; the dev split is unused.
- **Columns:** sentences in file order, in columns of 64 → 16 columns per language (15 × 64 + 1 × 52).
- **Methods:** raw HCC1, `sgtt` OpenAI200K Dense, `sgtt` Gemma3 Dense, P2b (frozen), P2c. Two runs, compared for determinism, plus the existing auditor.
- **Primary criterion (unchanged from `docs/phase2_proposal.md` §7):**
  - at least **5% fewer total stored bytes** than the per-column best `sgtt` baseline, summed over each language's columns, **for Hindi and for Kannada**;
  - **no evaluated group more than 5% worse**, including English;
  - medians, vocabulary cost, setup time and encoding speed are reported, but don't decide the outcome.
- **What is published:** `measurements_column.csv` without input or decoded text, aggregate summaries, and the manifest. **Not published:** `columns.tsv`, `containers.tsv`, `decoded_values.tsv` and `artifacts.tsv`, which contain FLORES+ text. They stay in the local storage path, outside Git. This needs a small runner option (§4.8).

### 4.7 Tests (to implement with P2c)
- Vocabulary invariants:
  - P2c IDs 0–5,247 equal P2a's;
  - every learned entry is at most 16 bytes, valid UTF-8, a single script plus an optional leading space, and aligned to akshara boundaries;
  - no duplicates; exactly 65,536 entries;
  - the table ID equals the SHA-256 prefix.
- Determinism: two builds give the same SHA-256, and a fixed toy corpus has a golden checksum. The builder test uses a small **synthetic** corpus in `tests/`, never real data.
- Exact round trips: empty input and empty values, NUL, LF/CR/CRLF/tab, emoji, invalid UTF-8, all 256 byte values, mixed Hindi/Kannada/English text, every prefix cut including cuts inside a code point or akshara, and long repetitive input.
- Longest match prefers learned entries, without crossing a value boundary inside HCC1.
- Malformed input: everything the P2b decoder already rejects, plus a P2c blob given the P2b vocabulary being rejected (different table ID).
- Accounting: reported components equal serialized sizes.
- Leakage: no learned entry is a whole FLORES+ sentence. This is checked locally against the hash set; the data stays local.

### 4.8 Code changes P2c would need (after approval)
- `codec/p2c/build_vocabulary.py`: corpus manifest in, frozen vocabulary out. Its only inputs are the approved training corpus and the frozen P2a vocabulary.
- The harness gets a seventh method, `p2c_learned`: HCC1 codec 3 with the P2c vocabulary.
- `run_column_benchmark.py` gets:
  - an external-dataset option that reads a FLORES+ manifest and local files;
  - a `--no-text-artifacts` mode that writes the text-bearing artifacts to the local storage path instead of `results/`.
- An evaluation script modelled on `benchmarks/phase2/evaluate_p2b.py`.

## 5. Recording data versions without committing content
- For each external dataset, commit `datasets/external_manifests/<name>_<version>.json` containing: source URL, version, retrieval date, the Hugging Face revision or dump date, licence string, file paths relative to the storage root, byte sizes and SHA-256s.
- The runner verifies the local files against the manifest before every run, as it already does for the controlled datasets.

## 6. Out of scope for the initial P2c criterion
- **Kannada–English code-mixed evaluation:** excluded by owner decision, and listed as future work. No source was found.
- **Hindi–English code-mixed evaluation:** also not part of the criterion. Candidates (COMI-LINGUA, L3Cube-HingCorpus) still need a licence check.
- Linux x86-64, sanitizer runs and native-speaker review remain outstanding, as before.

## 7. Sources (read 2026-10-24)
- IIT Bombay English–Hindi corpus: https://www.cfilt.iitb.ac.in/iitb_parallel/
- LDC-IL Kannada raw text corpus: https://data.ldcil.org/a-gold-standard-kannada-raw-text-corpus
- AI4Bharat Sangraha: https://huggingface.co/datasets/ai4bharat/sangraha
- AI4Bharat IndicCorp v2: https://huggingface.co/datasets/ai4bharat/IndicCorpV2
- Wikimedia dumps licensing: https://dumps.wikimedia.org/legal.html
- Leipzig Corpora Collection: https://wortschatz.uni-leipzig.de/en/download (not readable: bot check)
- FLORES+: https://huggingface.co/datasets/openlanguagedata/flores_plus (public card only; gate not accepted)
- Background on ILCI: https://aclanthology.org/L10-1602/

## 8. Decisions required from the project owner before implementation
The consolidated, pending checklist is now `docs/phase2_p2c_report.md` §8. Nothing in it is approved.

1. **Training source:** approve one source from §2 for P2c vocabulary learning, with its version or dump date. The suggestion is Wikipedia `hiwiki` + `knwiki`, *provided* the owner accepts CC BY-SA 4.0 (with attribution) for the published vocabulary file. Alternatively, ask a provider to clarify their terms first.
2. **Commercial status:** confirm whether ByteME/Hashcode is non-commercial. This decides whether CC BY-NC sources (IITB) are even eligible.
3. **FLORES+:** accept the gate yourself; approve evaluation-only use of version 4.6 devtest; approve the storage path `/Users/Shared/hashcode-data/` (outside every Git repository); approve the publication rule in §4.6 (aggregates only, no text-bearing artifacts).
4. **Decontamination:** confirm that using FLORES+ only as a training-data filter (§4.1) is acceptable, or decline it.
5. **P2c parameters:** approve the procedure in §4.2–4.4 before any data is touched. **Resolved proposal:**
   - candidates of 1 or more aksharas, at most 16 bytes;
   - the score with its tie-breaks;
   - a strict 50/50 split, with an `L` eligible only if both quotas fill;
   - `L` chosen on held-out training data by the equal-weight per-language ratio against P2b.

   This still needs the owner's approval (`docs/phase2_p2c_report.md` §3).
7. **Integrity checking:** P2b blobs (like P1, P2a and raw HCC1) carry no checksum, so some corruptions decode to wrong bytes without an error. Choose a policy (`docs/phase2_p2c_report.md` §3a). P2b's format and decoder are unchanged.
6. **Download size:** dumps and corpora can be large. Approve the specific download before it happens (CLAUDE.md rule 11).
