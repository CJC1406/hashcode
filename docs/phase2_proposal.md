# Phase 2: proposal (not approved)

**Status: proposal for approval.** No project document defines an official Phase 2. This document suggests one, based only on measured Phase 1 results (`docs/phase1_benchmark_report.md` §P).

**Progress (2026-10-24):** experiment 1, **P2a**, is implemented and measured on the controlled data only (`docs/phase2_p2a_report.md`).
- H1 is supported: fallback is cut sharply, and P2a is 16–25% smaller than P1 for the Indic groups.
- P2a is still 55% larger than the best `sgtt` baseline by total bytes.
- The §7 real-data criterion remains **blocked** on D3.
- P2b–P2d are not implemented.
- The criteria in §7 are unchanged.

## 1. What Phase 1 showed
- **Phase 1 passed on its pre-registered gate.** P1 met D2, the median reduction against the best `sgtt` baseline, in 5 of 5 groups on controlled data.
- **The pass comes from fixed per-column cost, not tokenization.** In all 29 columns where P1 beat `sgtt`, it spent more bytes on token IDs; it won only by having no bitmap and a smaller footer. **Byte-weighted, P1 stored 88.8% more than the best `sgtt` baseline.**
- **Two concrete weaknesses of P1:**
  1. one akshara (3–6 bytes) per 2-byte ID, where `sgtt` uses word-level tokens of up to 16 bytes with 1–2-byte IDs;
  2. spaces between Indic words fall back to single-byte IDs, which is 63–87% of P1's fallback tokens.
- **`sgtt` is weak on small columns.** Its Dense bitmap (25–153 B) plus a 24-byte footer makes it larger than raw on 17 of 24 `en-mixed` columns and 4 of 16 `kn-hi` columns.
- **The controlled datasets aren't real data,** so no language-level conclusion is possible yet (D3 is open).

## 2. Research question and hypotheses
**Question:** can a static, script-aware token table that combines low fixed per-column cost with longer Indic tokens store real Hindi, Kannada and code-mixed text columns in fewer **total bytes** than the best `sgtt` baseline, while reconstructing them exactly?

| ID | Hypothesis | Phase 1 evidence motivating it |
|---|---|---|
| H1 | Adding entries that combine a space with an akshara cuts P1's fallback tokens by at least half | fallback is 24% of tokens, and 63–87% of fallbacks are spaces |
| H2 | Per-column ID width (1 byte when a column uses ≤256 distinct IDs) plus a compact used-ID list instead of a full-vocabulary bitmap keeps P1's small-column advantage and shrinks its IDs | P1 wins only on fixed cost; `sgtt`'s bitmap costs 25–153 B per column |
| H3 | Multi-akshara and word entries derived from a *training* corpus (never from evaluation data) bring Indic bytes per token close to `sgtt` | `sgtt` averages about 8 bytes per token on Indic text; P1 is ≤6 |
| H4 | Choosing per column between raw and the token codec (a 1-byte flag) never stores more than raw plus 1 byte | raw was the smallest on 7 of 40 P1 evaluation columns |

## 3. Experimental changes (one variable at a time; each is a new frozen vocabulary or format version)
| Variant | Change | Needs data? |
|---|---|---|
| P1 | unchanged reference (`p1-akshara-ascii-v1`) | no |
| P2a | P1 plus a space+akshara entry for every existing akshara entry; fewer ASCII entries to stay within 65,536 | no (structural) |
| P2b | P2a plus per-column ID width and a used-ID list (new HCC1 codec version) | no |
| P2c | P2b plus multi-akshara/word entries chosen by frequency on a **training split** | **yes**: an approved training corpus, separate from evaluation |
| P2d | P2c plus a per-column choice between raw and the token codec | no |

**Held constant:**
- the HCC1 container and length table;
- the frozen `sgtt` baselines (raw, OpenAI200K Dense, Gemma3 Dense, upstream `e202e36` plus the build patch);
- greedy longest-prefix matching;
- no Unicode normalization;
- Release build flags and machine;
- the datasets, by checksum.

## 4. Data and permissions required (blocking: D3)
- **Evaluation:**
  - FLORES+ `devtest` for `eng_Latn`, `hin_Deva`, `kan_Knda` (CC BY-SA 4.0, gated, evaluation-only, no public redistribution).
  - It must not be committed. Store it outside the repository or in a git-ignored path, and record the version and SHA-256 of every file used.
  - Columns would be built from sentences in a fixed order, for example 64-sentence columns.
- **Training (P2c only):** a source whose licence permits deriving a vocabulary. IndicCorp v2 is labelled CC0, but the copyright of its crawled text must be clarified first. FLORES+ **must not** be used for training.
- **Code-mixed:**
  - No Kannada–English source was found.
  - Hindi–English candidates (COMI-LINGUA, L3Cube-HingCorpus) need licence checks.
  - Without one, code-mixed results stay on the controlled `phase1-en-mixed-v1` and are labelled as such.
- **Kept as regression tests:** the existing controlled datasets.
- **Approval needed before any download** (CLAUDE.md rule 11).

## 5. Baselines and metrics
- **Baselines:** raw HCC1, `sgtt` OpenAI200K Dense and `sgtt` Gemma3 Dense, unchanged. Optionally add `sgtt` Sparse, with the minimum taken over all configurations, stated explicitly.
- **Primary metric (byte-weighted):** for each language group, `Σ total_stored_bytes` over a declared set of non-overlapping evaluation columns, compared against the same sum for the per-column best `sgtt` baseline.
- **Secondary metrics:**
  - the median per-column reduction (the Phase 1 D2 statistic, kept for continuity);
  - wins and losses per column against raw;
  - bytes per token and fallback rate;
  - vocabulary size and break-even column size;
  - setup, encode, decoder-setup and decode times.

## 6. Correctness and performance tests
- All existing suites must still give their known results:
  - `hashcode_p1_tests` and `hashcode_column_tests` must all pass;
  - the round-trip suite must show the same 7 known failures;
  - the upstream suite must show the same 2.
- New unit tests for each variant: empty input, NUL, invalid UTF-8, all bytes, prefix cuts, the ID-width boundary at 256/257 distinct IDs, the raw/codec flag, and malformed-container rejection.
- An ASan/UBSan run of the P1/P2 codec and the column tests. Disk space now allows it.
- A Linux x86-64 run of the baselines and P2, to check that results don't depend on the platform.
- Two runs for each configuration, with 0 differences in non-timing columns, and an independent audit with 0 problems.

## 7. Success criteria (to be fixed and approved before any Phase 2 measurement)
**Proposed.** A variant succeeds on real evaluation data if all of these hold:
1. exact reconstruction on 100% of values;
2. a **byte-weighted reduction of at least 5% against the best `sgtt` baseline in both `hi` and `kn`**;
3. no group that is evaluated (including `en`) regresses by more than 5% byte-weighted;
4. the vocabulary is reported, and the break-even column size under the stated sharing assumption is given.

- The median criterion (D2) is reported, but **doesn't decide** the outcome.
- Results on the controlled datasets alone can't meet this criterion.
- **Failure handling:** if no variant meets it, Phase 2 reports a negative result, and the criterion is not changed after the fact.

## 8. Risks and dependencies
| Risk | Mitigation |
|---|---|
| D3 is never approved, or the licences don't permit use | Phase 2 stays on controlled data and makes no language claims; the decision goes back to the user |
| Vocabulary leakage from evaluation into training | separate sources, recorded SHA-256s, and a test that no evaluation sentence appears as a vocabulary entry |
| Per-column ID width reintroduces a size-dependent special case (as in Finding 4) | one rule for every column, no exceptions, and a boundary test at 256/257 IDs |
| Over-fitting to a few synthetic columns | the primary metric is byte-weighted, on real data, with the column set declared in advance |
| The disk filling up again (Phase 0) | check free space before sanitizer builds and keep builds in the scratchpad |
| Two Git roots (`/Users/cjc` and the project) | run project Git commands only from `/Users/cjc/Downloads/hashcode` |

## 9. Rollback and reproducibility
- Every variant is a new versioned vocabulary file with a SHA-256 table ID, and a new HCC1 codec value or version. P1 and the baselines stay runnable unchanged.
- Runs go into new `results/phase2/<run_id>/` directories. Existing results are never overwritten.
- Each run records its dataset checksums, vocabulary SHA-256, the upstream commit and patch, the compiler, flags and host (as in Phase 1).
- To roll back, select the previous vocabulary or codec version; no data migration is needed.

## 10. Decisions needed from the user
1. Approve or amend this proposal and its §7 success criteria.
2. D3: approve FLORES+ for evaluation-only use, the storage location, and a training source, if any.
3. Whether a Kannada–English code-mixed source should be sought or created (and by whom), or code-mixed claims left out.
