# Phase 1 Column Protocol: HCC1 container

## Why a project-owned container
- Upstream `sgtt` has **no native column API**.
  - `SGTTCompressor` doesn't override the multi-string `Compressor::compress(std::span<const std::string_view>, …)`; the base version throws "not implemented".
  - Upstream's `tools/sgtt.cpp` encodes a column file as **one buffer**, with values separated by `\n` inside the data. It splits lines only for compressors that implement the multi-string API.
- Newline separation can't represent values that contain `\n`, and it leaves value boundaries implicit.
- So HCC1 wraps the **unmodified** upstream blob in an explicit length table. Upstream's algorithms and blob format are untouched.

The implementation is `benchmarks/phase1/column_format.hpp`. It is used by `phase1_column_harness` and by `tests/column/ColumnFormatTest.cpp`, and an independent Python parser lives in `benchmarks/phase1/run_column_benchmark.py`.

## Layout (version 1)
| Field | Size | Accounted as |
|---|---|---|
| magic `HCC1` | 4 bytes | `header_bytes` |
| version `0x01` | 1 byte | `header_bytes` |
| codec: `0x00` raw, `0x01` sgtt, `0x02` P1/P2a (`codec/p1/README.md`; blob = `uint16` IDs + 13-byte `BTT1` footer), `0x03` P2b (`docs/phase2_p2b_report.md`; width byte, optional sorted `u16` mapping, `u8` or `u16` IDs, 13-byte `BTT2` footer) | 1 byte | `header_bytes` |
| `value_count` | unsigned LEB128 varint | `boundary_metadata_bytes` |
| one byte length per value, in order | `value_count` × varint | `boundary_metadata_bytes` |
| `blob_length` | varint | `boundary_metadata_bytes` |
| blob | `blob_length` bytes | see below |

**Blob:**
- **raw:** all value bytes concatenated, in order, with no separators.
- **sgtt:** the exact output of upstream `Compressor::compress` applied to that same concatenation.
  - The input is passed with 16 zero bytes of padding after it, as in upstream `test/Tester.hpp`. The padding is not stored.
  - The blob splits into token IDs (`encoded_payload_bytes`), the Dense bitmap (`bitmap_bytes`), and the 24-byte upstream footer (`footer_bytes`).
  - It is not stored at all (`blob_length = 0`, codec not called) when the concatenated payload is 0 bytes. Upstream asserts its input is non-empty, so this is how the wrapper respects that precondition without changing upstream.

**Semantics:**
- **Order:** values are kept exactly in input order.
- **Boundaries:** values are recovered only from the length table, by splitting the decoded concatenation. They never come from delimiter bytes, so NUL, `\n` or any other byte inside a value is fine.
- **Empty values:** a length of 0. Any number of them, in any position, round-trip correctly.
  - A column with zero values is `count = 0` and `blob_length = 0`: 8 bytes in total.
  - A column of only empty values has a zero-length blob.
- **Decoder checks:** it rejects a bad magic, an unknown version or codec, truncated or overlong varints, `blob_length` not matching the remaining bytes, and decoded payload size not matching the sum of the length table.
- **Self-containment:**
  - Raw HCC1 is self-contained.
  - sgtt HCC1 depends on upstream's **shared static vocabulary**, which is compiled into `sgtt_core`. It is identified only by the tokenizer type inside the upstream footer; there's no checksum of the vocabulary in the container. Vocabulary bytes are reported separately.
- **Normalization:** none. Bytes are opaque.

## Byte accounting
`total_stored_bytes = header_bytes + boundary_metadata_bytes + encoded_payload_bytes + bitmap_bytes + footer_bytes`

This must equal the serialized container size. Both C++ and Python check it, and Python re-parses every container independently.

| Field | raw | sgtt |
|---|---|---|
| `encoded_payload_bytes` | = original payload | token IDs = `token_count × token_id_bytes`, from upstream `getInfo()` |
| `bitmap_bytes` | 0 | `blob − token IDs − 24` |
| `footer_bytes` | 0 | 24 if a blob exists, else 0 |
| `dictionary_bytes` (per column) | 0 | 0 |
| `shared_vocabulary_bytes` | 0 | OpenAI200K 3,332,170; Gemma3 4,275,024 |

Vocabulary in the comparisons:
- **Primary comparison:** the shared vocabulary is **not charged**, because it's a static asset shipped once with the codec. The rule is the same for every method; raw simply has no vocabulary.
- **One-shot comparison:** `*_oneshot` charges the full vocabulary to the single column.

## Methods
- `raw_utf8_column`: HCC1 with codec 0.
- `sgtt_openai200k_column`: HCC1 with codec 1, upstream `TokenizerConfig{tokenizer=OpenAI200K, tokenIdEncoding=DenseIds}`, otherwise defaults.
- `sgtt_gemma3_column`: the same with `tokenizer=Gemma3`.

Dense is upstream's default, and the only variant run in column mode. Sparse would be a straightforward addition.

## Columns: dataset `phase1-kn-hi-v1`, members in dataset file order
- **Full run (30 columns):**
  - `col-all`;
  - `col-hi-all`, `col-kn-all`;
  - `col-<category>` (both languages, 8 categories);
  - `col-<lang>-<category>` (16);
  - `col-zero-values` (no members);
  - `col-empty-values` (`hi-tiny-001`, `kn-tiny-001`, both empty);
  - `col-all-except-paragraph-x10` (all samples except `hi-repeated-004` and `kn-repeated-004`).
- **Smoke run (3 columns):** `col-smoke` (the 8 per-value smoke samples), `col-zero-values`, `col-empty-values`.
- The exact membership and positions of every run are in `column_membership.tsv` and `run_metadata.json` (`columns`).

**Identical input across methods:** `input_sequence_fnv1a64` is FNV-1a over (64-bit little-endian length, then the bytes) for each value in order. Python recomputes it from the dataset for every row, so order, boundaries and empty values are all covered by the check.

## Correctness checks per (column, method)
- The decoded value count equals the original count.
- Every decoded value equals the original bytes; the `exact_values` count is reported.
- The order is unchanged.
- The Python parse of the container matches the reported layout, and the length table equals the source value lengths.
- The raw blob equals the concatenated values.
- Over 7 repetitions, the container is byte-identical (`encoded_consistent_across_reps`).
- Across runs, `--compare` checks 21 non-timing columns.

## Timing (per repetition; median of 7, or 3 for smoke)
- `codec_init_ms`: `Compressor::create(config)` for the encoder. sgtt only.
- `column_encode_ms`: concatenation, upstream `compress`, and container serialization.
- `decoder_init_ms`: container parse plus `Compressor::create(config, blob)`. sgtt only; it is ~0 when there's no blob.
- `column_decode_ms`: upstream `decompress` plus splitting into values.

## Commands
```bash
cmake --build external/token-vldb2026/build-arm64 --target hashcode_column_tests phase1_column_harness
external/token-vldb2026/build-arm64/hashcode_tests/hashcode_column_tests
python3 -I benchmarks/phase1/run_column_benchmark.py --smoke
python3 -I benchmarks/phase1/run_column_benchmark.py --per-value-run results/phase1/<per-value run>
python3 -I benchmarks/phase1/run_column_benchmark.py --compare results/phase1/<A> results/phase1/<B>
```
