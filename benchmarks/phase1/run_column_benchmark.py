"""Phase 1 column-mode orchestrator: HCC1 columns with raw UTF-8, sgtt OpenAI200K and sgtt Gemma3 (Dense IDs).

Usage (from the project root):
  python3 -I benchmarks/phase1/run_column_benchmark.py --smoke
  python3 -I benchmarks/phase1/run_column_benchmark.py --per-value-run results/phase1/<per-value run>
  python3 -I benchmarks/phase1/run_column_benchmark.py --compare RUN_A RUN_B
Standard library only. Writes results/phase1/<run_id>/. Never overwrites an existing run directory.
"""
import argparse
import csv
import datetime
import json
import pathlib
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import run_benchmark as pv  # noqa: E402  (shared dataset loading, provenance and CSV helpers)

COLUMN_HARNESS = pv.UPSTREAM / "build-arm64" / "hashcode_benchmarks" / "phase1_column_harness"
METHOD_VOCAB = {"raw_utf8_column": None, "sgtt_openai200k_column": "openai200k", "sgtt_gemma3_column": "gemma3", "p1_akshara_column": "p1",
                "p2a_space_akshara_column": "p2a"}
METHOD_CODEC = {"raw_utf8_column": 0, "sgtt_openai200k_column": 1, "sgtt_gemma3_column": 1, "p1_akshara_column": 2, "p2a_space_akshara_column": 2}
METHOD_FOOTER = {"sgtt_openai200k_column": pv.SGTT_FOOTER_BYTES, "sgtt_gemma3_column": pv.SGTT_FOOTER_BYTES, "p1_akshara_column": 13,
                 "p2a_space_akshara_column": 13}
P1_VOCABULARY = "codec/p1/p1_vocabulary_v1.bin"
P2A_VOCABULARY = "codec/p2a/p2a_vocabulary_v1.bin"
PER_VALUE_METHOD = {"raw_utf8_column": "raw_utf8", "sgtt_openai200k_column": "sgtt_openai200k_dense", "sgtt_gemma3_column": "sgtt_gemma3_dense"}
DETERMINISTIC = ["column_id", "method", "value_count", "original_payload_bytes", "input_sequence_fnv1a64", "token_count", "token_id_bytes", "used_tokens",
                 "header_bytes", "boundary_metadata_bytes", "codec_blob_bytes", "encoded_payload_bytes", "bitmap_bytes", "footer_bytes", "total_stored_bytes",
                 "container_fnv1a64", "decoded_value_count", "decoded_sequence_fnv1a64", "exact_values", "roundtrip_exact", "status"]
HCC1_HEADER = 6


def build_columns(samples, smoke):
    """Deterministic column policy: members in dataset file order; groups listed in this fixed order."""
    order = [s["sample_id"] for s in samples]
    by_id = {s["sample_id"]: s for s in samples}
    pick = lambda pred: [sid for sid in order if pred(by_id[sid])]
    if smoke:
        columns = [("col-smoke", [sid for sid in order if sid in set(pv.SMOKE_IDS)]),
                   ("col-zero-values", []),
                   ("col-empty-values", ["hi-tiny-001", "kn-tiny-001"])]
    else:
        columns = [("col-all", order), ("col-hi-all", pick(lambda s: s["language"] == "hi")), ("col-kn-all", pick(lambda s: s["language"] == "kn"))]
        for cat in ["short", "medium", "long", "repeated", "punct_numerals", "mixed", "edge", "tiny"]:
            columns.append((f"col-{cat}", pick(lambda s, c=cat: s["category"] == c)))
        for lang in ["hi", "kn"]:
            for cat in ["short", "medium", "long", "repeated", "punct_numerals", "mixed", "edge", "tiny"]:
                columns.append((f"col-{lang}-{cat}", pick(lambda s, l=lang, c=cat: s["language"] == l and s["category"] == c)))
        columns += [("col-zero-values", []), ("col-empty-values", ["hi-tiny-001", "kn-tiny-001"]),
                    ("col-all-except-paragraph-x10", pick(lambda s: s["sample_id"] not in ("hi-repeated-004", "kn-repeated-004")))]
    return columns


EN_MIXED_LANGUAGES = ["en", "en-hi", "en-kn"]
EN_MIXED_CATEGORIES = ["short", "medium", "long", "repeated", "punct_numerals", "structured", "edge", "tiny"]
EN_MIXED_PARAGRAPH_X10 = ("en-repeated-004", "en-hi-repeated-003", "en-kn-repeated-003")
EN_MIXED_EMPTY = ["en-tiny-001", "en-hi-tiny-001", "en-kn-tiny-001"]


def build_columns_en_mixed(samples, smoke):
    """Column policy for phase1-en-mixed-v1; members in dataset file order. The 24 col-<language>-<category>
    columns form the non-overlapping evaluation set; all other columns overlap with them."""
    order = [s["sample_id"] for s in samples]
    by_id = {s["sample_id"]: s for s in samples}
    pick = lambda pred: [sid for sid in order if pred(by_id[sid])]
    if smoke:
        smoke_ids = ["en-short-001", "en-edge-002", "en-structured-002", "en-hi-medium-001", "en-hi-edge-002", "en-kn-medium-001", "en-kn-structured-001"] + EN_MIXED_EMPTY
        return [("col-smoke", [sid for sid in order if sid in set(smoke_ids)]), ("col-zero-values", []), ("col-empty-values", EN_MIXED_EMPTY)]
    columns = [("col-all", order)]
    columns += [(f"col-{lang}-all", pick(lambda s, l=lang: s["language"] == l)) for lang in EN_MIXED_LANGUAGES]
    columns.append(("col-mixed-all", pick(lambda s: s["language"] in ("en-hi", "en-kn"))))
    for lang in EN_MIXED_LANGUAGES:
        for cat in EN_MIXED_CATEGORIES:
            columns.append((f"col-{lang}-{cat}", pick(lambda s, l=lang, c=cat: s["language"] == l and s["category"] == c)))
    columns += [("col-zero-values", []), ("col-empty-values", EN_MIXED_EMPTY),
                ("col-all-except-paragraph-x10", pick(lambda s: s["sample_id"] not in EN_MIXED_PARAGRAPH_X10))]
    return columns


# Datasets selectable with --dataset; "kn-hi-v1" is the default and keeps the original behaviour.
DATASETS = {
    "kn-hi-v1": {"path": pv.DATASET, "sha": pv.DATASET_SHA, "columns": build_columns, "per_value_comparison": True},
    "en-mixed-v1": {"path": pv.ROOT / "datasets" / "phase1_en_mixed" / "en_mixed_v1.jsonl",
                    "sha": pv.ROOT / "datasets" / "phase1_en_mixed" / "en_mixed_v1.sha256",
                    "columns": build_columns_en_mixed, "per_value_comparison": False},
}


def load_dataset(path, sha_path):
    """Same checks as run_benchmark.load_dataset, for any dataset file in the shared schema."""
    expected = sha_path.read_text().split()[0]
    actual = pv.sha256_file(path)
    if actual != expected:
        sys.exit(f"dataset checksum mismatch: {actual} != {expected} ({sha_path})")
    samples = []
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        data = bytes.fromhex(r["utf8_hex"])
        if r["text"].encode("utf-8") != data or len(data) != r["utf8_bytes"]:
            sys.exit(f"{r['sample_id']}: text, hex and utf8_bytes disagree")
        data.decode("utf-8")
        r["bytes"] = data
        samples.append(r)
    ids = [s["sample_id"] for s in samples]
    if len(ids) != len(set(ids)):
        sys.exit("duplicate sample ids")
    return samples, actual


def sequence_fnv(values):
    h = 0xcbf29ce484222325
    for v in values:
        for b in len(v).to_bytes(8, "little") + v:
            h ^= b
            h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def get_varint(buf, pos):
    v, shift = 0, 0
    while True:
        b = buf[pos]
        pos += 1
        v |= (b & 0x7F) << shift
        if not b & 0x80:
            return v, pos
        shift += 7


def parse_hcc1(buf):
    """Independent Python parser for the HCC1 container."""
    if buf[:4] != b"HCC1" or buf[4] != 1:
        raise ValueError("bad HCC1 header")
    pos = HCC1_HEADER
    count, pos = get_varint(buf, pos)
    lengths = []
    for _ in range(count):
        n, pos = get_varint(buf, pos)
        lengths.append(n)
    blob_len, pos = get_varint(buf, pos)
    if blob_len != len(buf) - pos:
        raise ValueError("blob length mismatch")
    return {"codec": buf[5], "lengths": lengths, "boundary": pos - HCC1_HEADER, "blob": buf[pos:]}


def validate(columns, by_id, rows, containers, decoded, prov):
    problems, derived = [], []
    col_map = dict(columns)
    expected = {(cid, m) for cid, _ in columns for m in METHOD_VOCAB}
    if {(r["column_id"], r["method"]) for r in rows} != expected or len(rows) != len(expected):
        problems.append("rows do not cover every column x method exactly once")
    for r in rows:
        cid, m = r["column_id"], r["method"]
        members = col_map[cid]
        values = [by_id[sid]["bytes"] for sid in members]
        tag = f"{cid}/{m}"
        if int(r["value_count"]) != len(values) or int(r["original_payload_bytes"]) != sum(map(len, values)):
            problems.append(f"{tag}: value count or payload size mismatch")
        if int(r["input_sequence_fnv1a64"]) != sequence_fnv(values):
            problems.append(f"{tag}: harness received a different ordered value sequence")
        if r["status"] != "ok":
            problems.append(f"{tag}: status {r['status']} {r['error_message']}")
        else:
            parts = [int(r[c]) for c in ("header_bytes", "boundary_metadata_bytes", "encoded_payload_bytes", "bitmap_bytes", "footer_bytes")]
            total = int(r["total_stored_bytes"])
            if sum(parts) != total:
                problems.append(f"{tag}: components {parts} do not sum to {total}")
            buf = bytes.fromhex(containers[(cid, m)])
            if len(buf) != total:
                problems.append(f"{tag}: container size != total_stored_bytes")
            try:
                p = parse_hcc1(buf)
                if p["lengths"] != [len(v) for v in values]:
                    problems.append(f"{tag}: container length table differs from source values")
                if p["boundary"] != int(r["boundary_metadata_bytes"]) or len(p["blob"]) != int(r["codec_blob_bytes"]):
                    problems.append(f"{tag}: independently parsed layout differs from reported layout")
                if m == "raw_utf8_column" and p["blob"] != b"".join(values):
                    problems.append(f"{tag}: raw blob is not the concatenated values")
                if p["codec"] != METHOD_CODEC[m]:
                    problems.append(f"{tag}: codec byte")
            except Exception as e:  # noqa: BLE001
                problems.append(f"{tag}: Python HCC1 parse failed: {e}")
            if m == "raw_utf8_column" and (int(r["bitmap_bytes"]) or int(r["footer_bytes"]) or int(r["encoded_payload_bytes"]) != sum(map(len, values))):
                problems.append(f"{tag}: raw accounting")
            if m != "raw_utf8_column" and sum(map(len, values)) > 0 and int(r["footer_bytes"]) != METHOD_FOOTER[m]:
                problems.append(f"{tag}: codec footer size")
            got = decoded.get((cid, m), [])
            if [g[1] for g in got] != members or [bytes.fromhex(g[2]) for g in got] != values:
                problems.append(f"{tag}: independent per-value decoded check failed")
        vocab_name = METHOD_VOCAB[m]
        vocab = sum(f["bytes"] for f in prov["shared_vocabulary_files"][vocab_name].values()) if vocab_name else 0
        total = int(r["total_stored_bytes"]) if r["status"] == "ok" else None
        orig = int(r["original_payload_bytes"])
        ratio, red = pv.ratio_fields(orig, total)
        ratio_os, red_os = pv.ratio_fields(orig, total + vocab if total is not None else None)
        derived.append({**r, "member_sample_ids": " ".join(members), "dictionary_bytes": 0, "shared_vocabulary_bytes": vocab,
                        "vocabulary_amortization": "shared static asset, not charged" if vocab_name else "none (no vocabulary)",
                        "total_stored_bytes_oneshot_with_vocabulary": total + vocab if total is not None else "",
                        "compression_ratio": ratio, "size_reduction_percent": red,
                        "compression_ratio_oneshot": ratio_os, "size_reduction_percent_oneshot": red_os,
                        "dataset_version": next(iter(by_id.values()))["dataset_version"]})
    return derived, problems


def per_value_comparison(columns, derived, per_value_dir):
    with open(per_value_dir / "measurements.csv", encoding="utf-8") as f:
        pvrows = {(r["sample_id"], r["method"]): r for r in csv.DictReader(f)}
    out = []
    for r in derived:
        if r["method"] not in PER_VALUE_METHOD:
            continue  # no per-value counterpart (P1 exists only in column mode)
        members = r["member_sample_ids"].split() if r["member_sample_ids"] else []
        pm = PER_VALUE_METHOD[r["method"]]
        supported = [sid for sid in members if pvrows[(sid, pm)]["status"] == "ok"]
        pv_total = sum(int(pvrows[(sid, pm)]["total_stored_bytes"]) for sid in supported)
        orig = sum(int(pvrows[(sid, pm)]["original_bytes"]) for sid in members)
        out.append({"column_id": r["column_id"], "method": r["method"], "per_value_method": pm, "values": len(members),
                    "per_value_supported_values": len(supported), "per_value_unsupported_values": len(members) - len(supported),
                    "original_payload_bytes": orig, "per_value_sum_total_stored_bytes": pv_total if len(supported) == len(members) else "",
                    "per_value_sum_total_stored_bytes_supported_only": pv_total, "column_total_stored_bytes": r["total_stored_bytes"],
                    "per_value_aggregate_ratio": f"{orig / pv_total:.6f}" if pv_total and len(supported) == len(members) else "",
                    "column_ratio": r["compression_ratio"]})
    return out


def compare(a_dir, b_dir):
    def load(d):
        with open(d / "measurements_column.csv", encoding="utf-8") as f:
            return {(r["column_id"], r["method"]): r for r in csv.DictReader(f)}
    a, b = load(a_dir), load(b_dir)
    diffs = [f"{k}: {c} {a[k][c]!r} != {b[k][c]!r}" for k in sorted(set(a) | set(b)) for c in DETERMINISTIC if k not in a or k not in b or a[k][c] != b[k][c]]
    print(f"compared {len(a)} vs {len(b)} column rows on {len(DETERMINISTIC)} non-timing columns: {len(diffs)} differences")
    for d in diffs[:20]:
        print("  " + d)
    return 0 if not diffs and len(a) == len(b) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--repetitions", type=int, default=None, help="default 7, smoke 3")
    ap.add_argument("--harness", type=pathlib.Path, default=COLUMN_HARNESS)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--per-value-run", type=pathlib.Path, default=None, help="per-value run directory for the per-value vs column comparison")
    ap.add_argument("--compare", nargs=2, type=pathlib.Path, metavar=("RUN_A", "RUN_B"))
    ap.add_argument("--dataset", choices=sorted(DATASETS), default="kn-hi-v1")
    ap.add_argument("--results-root", type=pathlib.Path, default=pv.RESULTS, help="parent directory for the run (default results/phase1)")
    args = ap.parse_args()
    if args.compare:
        sys.exit(compare(*args.compare))

    dataset = DATASETS[args.dataset]
    if args.per_value_run and not dataset["per_value_comparison"]:
        sys.exit(f"--per-value-run is only defined for datasets with per-value runs (not {args.dataset})")
    samples, dataset_sha = load_dataset(dataset["path"], dataset["sha"])
    by_id = {s["sample_id"]: s for s in samples}
    columns = dataset["columns"](samples, args.smoke)
    reps = args.repetitions or (3 if args.smoke else 7)
    run_id = args.run_id or (("column-smoke-" if args.smoke else "column-full-") + datetime.datetime.now().strftime("%Y%m%dT%H%M%S"))
    out = args.results_root.resolve() / run_id
    out.mkdir(parents=True, exist_ok=False)

    with open(out / "columns.tsv", "w", encoding="ascii") as f:
        for cid, members in columns:
            f.write(f"C\t{cid}\t{len(members)}\n")
            for sid in members:
                f.write(f"V\t{sid}\t{by_id[sid]['utf8_hex']}\n")
    prov = pv.provenance(args.harness)
    prov["column_sources_sha256"] = {p: pv.sha256_file(pv.ROOT / p) for p in ("benchmarks/phase1/column_format.hpp", "benchmarks/phase1/column_harness.cpp", "codec/include/p1_codec.hpp")}
    for name, path in (("p1", P1_VOCABULARY), ("p2a", P2A_VOCABULARY)):
        prov["shared_vocabulary_files"][name] = {path: {"bytes": (pv.ROOT / path).stat().st_size, "sha256": pv.sha256_file(pv.ROOT / path)}}
    cmd = [str(args.harness), str(out / "columns.tsv"), str(out / "raw_column_harness.csv"), str(out / "containers.tsv"), str(out / "decoded_values.tsv"), str(reps)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    (out / "harness_stdout.txt").write_text(proc.stdout)
    (out / "harness_stderr.txt").write_text(proc.stderr)

    with open(out / "raw_column_harness.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with open(out / "containers.tsv", encoding="utf-8") as f:
        containers = {(r["column_id"], r["method"]): r["container_hex"] for r in csv.DictReader(f, delimiter="\t")}
    decoded = {}
    with open(out / "decoded_values.tsv", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            decoded.setdefault((r["column_id"], r["method"]), []).append((int(r["value_index"]), r["sample_id"], r["decoded_hex"]))
    derived, problems = validate(columns, by_id, rows, containers, decoded, prov)
    pv.write_csv(out / "measurements_column.csv", derived)
    with open(out / "column_membership.tsv", "w", encoding="utf-8") as f:
        f.write("column_id\tposition\tsample_id\tlanguage\tcategory\tutf8_bytes\n")
        for cid, members in columns:
            for i, sid in enumerate(members):
                f.write(f"{cid}\t{i}\t{sid}\t{by_id[sid]['language']}\t{by_id[sid]['category']}\t{by_id[sid]['utf8_bytes']}\n")
    if args.per_value_run:
        pv.write_csv(out / "per_value_vs_column.csv", per_value_comparison(columns, derived, args.per_value_run))
    def rel(p):
        """Repository-relative form of a path argument, so run metadata contains no machine-specific paths."""
        try:
            return str(pathlib.Path(p).resolve().relative_to(pv.ROOT))
        except ValueError:
            return str(p)
    prov["harness_binary"] = rel(prov["harness_binary"])
    meta = {"run_id": run_id, "mode": "column-smoke" if args.smoke else "column-full", "repetitions": reps, "command": [rel(c) for c in cmd], "harness_exit_code": proc.returncode,
            "dataset": {"name": args.dataset, "path": str(dataset["path"].relative_to(pv.ROOT)), "sha256": dataset_sha, "version": samples[0]["dataset_version"], "samples": len(samples)},
            "columns": {cid: members for cid, members in columns}, "per_value_run": str(args.per_value_run) if args.per_value_run else None,
            "validation_problems": problems, **prov}
    (out / "run_metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")

    statuses = {}
    for r in rows:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    print(f"run {run_id}: {len(columns)} columns x {len(METHOD_VOCAB)} methods = {len(rows)} rows; harness exit {proc.returncode}")
    print(f"statuses: {statuses}")
    print(f"validation problems: {len(problems)}")
    for p in problems[:20]:
        print("  " + p)
    print(f"output: {out}")
    sys.exit(0 if proc.returncode == 0 and not problems else 1)


if __name__ == "__main__":
    main()
