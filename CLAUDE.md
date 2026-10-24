# Token Tables for Bharat — Development Instructions

## Project objective
Research and implement lossless, script-aware token-table compression for Indian-language database strings.

The primary reference is "Accelerating String-Heavy Queries with LLM Token Tables" (PVLDB 2026). Additional references are BtrBlocks (SIGMOD 2023) and NNCP.

## Development environment
- macOS on Apple Silicon
- Antigravity IDE with Claude Code
- C++23 for reproducing the original implementation
- C++17 or later for our own codec, subject to design decisions
- Python 3 for dataset preparation and analysis
- CMake for builds
- Git for version control

## Repository structure
- research/: papers and technical notes
- external/: third-party reference implementations
- datasets/: corpora and test data
- codec/: proposed compression engine
- tests/: correctness and property-based tests
- benchmarks/: benchmark programs
- experiments/: evaluation scripts
- results/: measured outputs
- docs/: specifications and reports

## Rules
1. Work only on the currently assigned phase.
2. Read the relevant paper and source code before proposing algorithmic changes.
3. Do not modify code under external/ without explicit permission.
4. Do not invent benchmark results, citations, speedups, or compression ratios.
5. Never claim that an experimental hypothesis is proven without evidence.
6. Preserve exact lossless round-trip correctness.
7. Distinguish Unicode code points, UTF-8 bytes, and grapheme clusters.
8. Account for metadata, dictionary size, and fallback overhead in compression measurements.
9. Write tests for edge cases, mixed scripts, empty strings, invalid input, and Unicode handling.
10. Explain the rationale and trade-offs for each architectural decision.
11. Before executing destructive commands or downloading large datasets, request approval.
12. Maintain reproducible experiment configurations and record compiler versions, hardware, and dataset provenance.

## Workflow
For each phase:
1. Explain the objective.
2. Identify relevant research.
3. Propose implementation tasks.
4. Implement only approved tasks.
5. Run tests.
6. Record results and limitations.
7. Prepare a phase completion report.

## Project status (updated 2026-10-24)
Run project Git commands only from `/Users/cjc/Downloads/hashcode`. `/Users/cjc` is an unrelated repository.

**Phase 1: complete for controlled harness validation** (`docs/phase1_benchmark_report.md` §P).
- **P1** (`codec/p1/`, vocabulary SHA-256 `8c85586c…`):
  - Exact reconstruction (7,652 test assertions; 248 / 248 benchmark rows).
  - Deterministic vocabulary built without evaluation data; repeat runs identical.
  - Met the pre-registered D2 median criterion in 5 / 5 language groups.
- **But it is not a better codec:** byte-weighted over 40 columns, P1 is 88.8% larger than the best `sgtt` baseline (23,223 vs 12,300 bytes). Its encoding is about 3× slower, and about 24% of its tokens are single-byte fallbacks, mostly spaces.

**Current phase: Phase 2** (`docs/phase2_proposal.md`, proposal not yet approved).
- **Hypothesis H1:** space+akshara entries cut fallback.
- **First experiment: P2a** (`codec/p2a/`, SHA-256 `c99ff52f…`), which is frozen P1 plus space+akshara entries.
  - On the controlled data it cut fallback sharply and was 16–25% smaller than P1 for the Indic groups.
  - It is still 55% larger than `sgtt` (19,090 vs 12,300 bytes; `docs/phase2_p2a_report.md`).
- **Second experiment: P2b** (per-column ID width, HCC1 codec 3, P2a vocabulary unchanged).
  - 30.2% smaller than P2a, but still **8.4% larger than `sgtt`** (13,331 vs 12,300 bytes; `docs/phase2_p2b_report.md`).
  - It beats `sgtt` for `en` and `en-hi`, and loses by about 30% for `hi` and `kn`, where it needs 1.6–2.0× as many tokens.
- **Third experiment: P2c** (learned multi-akshara/word entries): the builder, codec integration (unchanged P2b codec, new vocabulary table ID) and tests are implemented and tested on synthetic and controlled data only (`docs/phase2_p2c_report.md`). **No P2c vocabulary is frozen and no P2c benchmark was run**, because there is no approved training corpus. Its design decisions (D1–D8, report §3) are resolved but await owner approval. P2b's lack of a checksum is a separate open decision (report §3a). The pending approval checklist is in report §8, and the read-only training-source review (Sangraha, Wikipedia, IndicCorp v2) is in report §9. The decision sheet is in report §10. The owner approved D1–D8, the corruption policy, Wikipedia 20261001 (CC BY-SA 4.0 vocabulary) and its download. FLORES+ and commits are not approved. The converter, checker and pipeline are in report §11. **The P2c vocabulary is frozen:** `codec/p2c/p2c_vocabulary_v1.bin`, SHA-256 `1e12dc48…`, L = 32,768, 16,384 + 16,384 learned entries, deterministic, checker OK. It is **not evaluated** yet; FLORES+ isn't approved. Controlled-data harness demo (not evidence): `docs/phase2_p2c_demo.md`; P2c 9,061 B against best `sgtt` 12,300 B over 40 columns. The independent evaluation workflow is prepared but not run: `docs/phase2_p2c_evaluation.md`. It waits for the owner's FLORES+ approvals.
- **P2c data status:** the plan and licence review are in `docs/phase2_p2c_plan.md`. **No training source is approved yet.** FLORES+ is a conditional candidate for evaluation only (the owner must accept the gate, approve storage outside every Git repo, and approve publishing aggregates only). Kannada–English code-mixed evaluation is excluded from the initial criterion.

**Plan C (separate track: native LLM token reduction), tokenizer-only prototype:** `experiments/indic_tokenizer/` and `docs/indic_tokenizer.md`.
- It extends Qwen3's own tokenizer with ByteME-derived Indic tokens (added tokens, new IDs from 151,669) chosen on the Wikipedia training split.
- Measured on the Wikipedia held-out split, which is the same source and not independent: B = 36.8% fewer native Qwen3 tokens for Hindi and 45.9% for Kannada, with exact round trips. Independent FLORES+ evaluation is blocked (approvals false), so the 20% target is unverified.
- No model, inference, speed or quality has been measured; weights, torch and compute are not available or approved.
- ByteME storage IDs are never given to a model.

**Unproven:** any effectiveness on real Hindi, Kannada or code-mixed text.

**Outstanding:**
- D3 real-data approval: FLORES+ for evaluation only; a training source; a Kannada–English code-mixed source.
- Linux x86-64 testing.
- Sanitizer runs of the P1/P2a and column code.
- Native-speaker review of the controlled datasets.
- Both controlled datasets are for harness validation only.
