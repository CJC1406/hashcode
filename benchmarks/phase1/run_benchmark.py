"""Phase 1 benchmark orchestrator: raw UTF-8 vs upstream sgtt (OpenAI200K, Gemma3) on the frozen Kannada/Hindi dataset.

Usage (from the project root):
  python3 -I benchmarks/phase1/run_benchmark.py --smoke
  python3 -I benchmarks/phase1/run_benchmark.py --repetitions 7
  python3 -I benchmarks/phase1/run_benchmark.py --compare RUN_DIR_A RUN_DIR_B
Standard library only. Writes results/phase1/<run_id>/.
"""
import argparse
import csv
import datetime
import hashlib
import json
import pathlib
import platform
import statistics
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / "external" / "token-vldb2026"
DEFAULT_HARNESS = UPSTREAM / "build-arm64" / "hashcode_benchmarks" / "phase1_harness"
DATASET = ROOT / "datasets" / "phase1" / "kn_hi_v1.jsonl"
DATASET_SHA = ROOT / "datasets" / "phase1" / "kn_hi_v1.sha256"
RESULTS = ROOT / "results" / "phase1"

SMOKE_IDS = ["hi-short-001", "hi-mixed-001", "hi-edge-002", "hi-tiny-001", "kn-short-001", "kn-medium-001", "kn-edge-001", "kn-tiny-001"]
# Static vocabulary assets compiled into sgtt_core; shared by every encoded value, never stored per value.
SHARED_VOCABULARY = {
    "openai200k": ["src/tokens/openai200k/openai200k_dict.bin", "src/tokens/openai200k/openai200k_lengths.bin"],
    "gemma3": ["src/tokens/gemma3/gemma3_dict.bin", "src/tokens/gemma3/gemma3_lengths.bin"],
}
DETERMINISTIC_COLUMNS = ["sample_id", "method", "original_bytes", "input_fnv1a64", "token_count", "token_id_bytes", "used_tokens", "payload_bytes",
                         "metadata_bytes", "footer_bytes", "bitmap_bytes", "total_stored_bytes", "encoded_fnv1a64", "decoded_bytes", "decoded_fnv1a64",
                         "roundtrip_exact", "status"]
SGTT_FOOTER_BYTES = 24


def fnv1a64(data: bytes) -> int:
    h = 0xcbf29ce484222325
    for b in data:
        h ^= b
        h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(cmd, cwd=None) -> str:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True).stdout.strip()


def load_dataset():
    expected = DATASET_SHA.read_text().split()[0]
    actual = sha256_file(DATASET)
    if actual != expected:
        sys.exit(f"dataset checksum mismatch: {actual} != {expected} ({DATASET_SHA})")
    samples = []
    for line in DATASET.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        data = bytes.fromhex(r["utf8_hex"])
        if r["text"].encode("utf-8") != data or len(data) != r["utf8_bytes"]:
            sys.exit(f"{r['sample_id']}: text, hex and utf8_bytes disagree")
        data.decode("utf-8")  # language benchmark inputs must be valid UTF-8
        r["bytes"] = data
        samples.append(r)
    ids = [s["sample_id"] for s in samples]
    if len(ids) != len(set(ids)):
        sys.exit("duplicate sample ids")
    return samples, actual


def ratio_fields(original: int, total):
    if total in (None, "") or original == 0:
        return "", ""
    total = int(total)
    if total == 0:
        return "", ""
    return f"{original / total:.6f}", f"{(original - total) / original * 100:.4f}"


def provenance(harness: pathlib.Path):
    upstream_dirty = run(["git", "-C", str(UPSTREAM), "status", "--short", "--untracked-files=no"]).splitlines()
    cache = (UPSTREAM / "build-arm64" / "CMakeCache.txt").read_text().splitlines()
    flags = {k: v for line in cache for k, _, v in [line.partition("=")] if k.split(":")[0] in ("CMAKE_BUILD_TYPE", "CMAKE_CXX_FLAGS", "CMAKE_EXE_LINKER_FLAGS", "CMAKE_CXX_FLAGS_RELEASE")}
    return {
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "host": {"os": run(["sw_vers", "-productVersion"]), "os_build": run(["sw_vers", "-buildVersion"]), "machine": platform.machine(),
                 "cpu": run(["sysctl", "-n", "machdep.cpu.brand_string"]), "logical_cpus": run(["sysctl", "-n", "hw.ncpu"])},
        "compiler": run(["c++", "--version"]).splitlines()[0],
        "cmake": run(["cmake", "--version"]).splitlines()[0],
        "python": platform.python_version(),
        "build_flags": flags,
        "upstream": {"remote": run(["git", "-C", str(UPSTREAM), "remote", "get-url", "origin"]), "commit": run(["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"]),
                     "branch": run(["git", "-C", str(UPSTREAM), "branch", "--show-current"]), "uncommitted_tracked_changes": upstream_dirty},
        "harness_binary": str(harness), "harness_sha256": sha256_file(harness),
        "harness_source_sha256": sha256_file(ROOT / "benchmarks" / "phase1" / "harness.cpp"),
        "shared_vocabulary_files": {name: {p: {"bytes": (UPSTREAM / p).stat().st_size, "sha256": sha256_file(UPSTREAM / p)} for p in paths} for name, paths in SHARED_VOCABULARY.items()},
    }


def vocabulary_bytes(method: str, prov) -> str:
    for name, files in prov["shared_vocabulary_files"].items():
        if f"_{name}_" in f"{method}_":
            return str(sum(f["bytes"] for f in files.values()))
    return ""


def validate_and_derive(samples, rows, artifacts, prov):
    by_id = {s["sample_id"]: s for s in samples}
    problems = []
    methods = sorted({r["method"] for r in rows})
    expected_pairs = {(s["sample_id"], m) for s in samples for m in methods}
    if {(r["sample_id"], r["method"]) for r in rows} != expected_pairs or len(rows) != len(expected_pairs):
        problems.append("rows do not cover every sample x method exactly once")
    derived = []
    for r in rows:
        s = by_id[r["sample_id"]]
        data = s["bytes"]
        if int(r["original_bytes"]) != len(data):
            problems.append(f"{r['sample_id']}/{r['method']}: original_bytes mismatch")
        if int(r["input_fnv1a64"]) != fnv1a64(data):
            problems.append(f"{r['sample_id']}/{r['method']}: harness received different input bytes")
        if r["status"] == "ok":
            total, payload, meta = int(r["total_stored_bytes"]), int(r["payload_bytes"]), int(r["metadata_bytes"])
            if payload + meta != total:
                problems.append(f"{r['sample_id']}/{r['method']}: payload + metadata != total")
            if r["method"].startswith("sgtt_"):
                if int(r["footer_bytes"]) != SGTT_FOOTER_BYTES or int(r["bitmap_bytes"]) < 0:
                    problems.append(f"{r['sample_id']}/{r['method']}: footer/bitmap accounting")
                if r["method"].endswith("_sparse") and int(r["bitmap_bytes"]) != 0:
                    problems.append(f"{r['sample_id']}/{r['method']}: sparse encoding has bitmap bytes")
                if payload != int(r["token_count"]) * int(r["token_id_bytes"]):
                    problems.append(f"{r['sample_id']}/{r['method']}: payload != tokens x id size")
                art = artifacts.get((r["sample_id"], r["method"]))
                if art is None:
                    problems.append(f"{r['sample_id']}/{r['method']}: missing artifact")
                else:
                    if len(art["encoded_hex"]) != 2 * total:
                        problems.append(f"{r['sample_id']}/{r['method']}: artifact size != total_stored_bytes")
                    if bytes.fromhex(art["decoded_hex"]) != data:
                        problems.append(f"{r['sample_id']}/{r['method']}: independent decoded-bytes check failed")
        vocab = vocabulary_bytes(r["method"], prov)
        total = r["total_stored_bytes"]
        oneshot = str(int(total) + int(vocab)) if total and vocab else (total if r["method"] == "raw_utf8" else "")
        ratio, reduction = ratio_fields(len(data), total)
        ratio_os, reduction_os = ratio_fields(len(data), oneshot)
        out = {"language": s["language"], "category": s["category"], **r,
               "shared_vocabulary_bytes": vocab if vocab else ("0" if r["method"] == "raw_utf8" else ""),
               "total_stored_bytes_oneshot_with_vocabulary": oneshot,
               "compression_ratio": ratio, "size_reduction_percent": reduction,
               "compression_ratio_oneshot": ratio_os, "size_reduction_percent_oneshot": reduction_os,
               "dataset_version": s["dataset_version"]}
        derived.append(out)
    return derived, problems


def summarize(derived):
    groups = {}
    for r in derived:
        for key in [(r["language"], r["category"], r["method"]), (r["language"], "ALL", r["method"])]:
            groups.setdefault(key, []).append(r)
    summary = []
    for (language, category, method), rs in sorted(groups.items()):
        ok = [r for r in rs if r["status"] == "ok"]
        measurable = [r for r in ok if r["compression_ratio"]]
        orig = sum(int(r["original_bytes"]) for r in measurable)
        tot = sum(int(r["total_stored_bytes"]) for r in measurable)
        med = lambda col: f"{statistics.median(float(r[col]) for r in ok if r[col]):.6f}" if any(r[col] for r in ok) else ""
        summary.append({
            "language": language, "category": category, "method": method, "samples": len(rs), "ok": len(ok),
            "unsupported": sum(r["status"] == "unsupported_input" for r in rs), "failed": sum(r["status"] not in ("ok", "unsupported_input") for r in rs),
            "roundtrip_exact": sum(r["roundtrip_exact"] == "true" for r in ok), "measurable_for_ratio": len(measurable),
            "sum_original_bytes": orig, "sum_total_stored_bytes": tot,
            "aggregate_compression_ratio": f"{orig / tot:.6f}" if tot else "",
            "aggregate_size_reduction_percent": f"{(orig - tot) / orig * 100:.4f}" if orig else "",
            "median_compression_ratio": f"{statistics.median(float(r['compression_ratio']) for r in measurable):.6f}" if measurable else "",
            "median_size_reduction_percent": f"{statistics.median(float(r['size_reduction_percent']) for r in measurable):.4f}" if measurable else "",
            "median_tokens": f"{statistics.median(int(r['token_count']) for r in ok if r['token_count']):.1f}" if any(r["token_count"] for r in ok) else "",
            "median_encode_ms": med("encode_ms_median"), "median_decode_ms": med("decode_ms_median"),
            "median_setup_encode_ms": med("setup_encode_ms_median"), "median_setup_decode_ms": med("setup_decode_ms_median"),
        })
    return summary


def write_csv(path, rows, fields=None):
    fields = fields or list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def compare(dir_a: pathlib.Path, dir_b: pathlib.Path) -> int:
    def load(d):
        with open(d / "measurements.csv", encoding="utf-8") as f:
            return {(r["sample_id"], r["method"]): r for r in csv.DictReader(f)}
    a, b = load(dir_a), load(dir_b)
    diffs = [f"{k}: {c} {a[k][c]!r} != {b[k][c]!r}" for k in sorted(set(a) | set(b)) for c in DETERMINISTIC_COLUMNS
             if k not in a or k not in b or a[k][c] != b[k][c]]
    print(f"compared {len(a)} vs {len(b)} rows on {len(DETERMINISTIC_COLUMNS)} non-timing columns: {len(diffs)} differences")
    for d in diffs[:20]:
        print("  " + d)
    return 0 if not diffs and len(a) == len(b) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="run 8 fixed samples only")
    ap.add_argument("--repetitions", type=int, default=None, help="timed repetitions per sample and method (default 7, smoke 3)")
    ap.add_argument("--harness", type=pathlib.Path, default=DEFAULT_HARNESS)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--compare", nargs=2, type=pathlib.Path, metavar=("RUN_A", "RUN_B"))
    args = ap.parse_args()
    if args.compare:
        sys.exit(compare(*args.compare))

    samples, dataset_sha = load_dataset()
    if args.smoke:
        wanted = set(SMOKE_IDS)
        samples = [s for s in samples if s["sample_id"] in wanted]
        if len(samples) != len(SMOKE_IDS):
            sys.exit("smoke sample ids missing from dataset")
    reps = args.repetitions or (3 if args.smoke else 7)
    run_id = args.run_id or (("smoke-" if args.smoke else "full-") + datetime.datetime.now().strftime("%Y%m%dT%H%M%S"))
    out = RESULTS / run_id
    out.mkdir(parents=True, exist_ok=False)

    with open(out / "input.tsv", "w", encoding="ascii") as f:
        for s in samples:
            f.write(f"{s['sample_id']}\t{s['utf8_hex']}\n")
    prov = provenance(args.harness)
    cmd = [str(args.harness), str(out / "input.tsv"), str(out / "raw_harness.csv"), str(out / "artifacts.tsv"), str(reps)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    (out / "harness_stdout.txt").write_text(proc.stdout)
    (out / "harness_stderr.txt").write_text(proc.stderr)

    with open(out / "raw_harness.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with open(out / "artifacts.tsv", encoding="utf-8") as f:
        artifacts = {(r["sample_id"], r["method"]): r for r in csv.DictReader(f, delimiter="\t")}
    derived, problems = validate_and_derive(samples, rows, artifacts, prov)
    write_csv(out / "measurements.csv", derived)
    write_csv(out / "summary.csv", summarize(derived))
    meta = {"run_id": run_id, "mode": "smoke" if args.smoke else "full", "repetitions": reps, "command": cmd, "harness_exit_code": proc.returncode,
            "dataset": {"path": str(DATASET.relative_to(ROOT)), "sha256": dataset_sha, "version": samples[0]["dataset_version"], "samples": len(samples)},
            "validation_problems": problems, **prov}
    (out / "run_metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")

    statuses = {}
    for r in derived:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    print(f"run {run_id}: {len(samples)} samples x {len({r['method'] for r in rows})} methods = {len(rows)} rows; harness exit {proc.returncode}")
    print(f"statuses: {statuses}")
    print(f"validation problems: {len(problems)}")
    for p in problems[:20]:
        print("  " + p)
    print(f"output: {out}")
    sys.exit(0 if proc.returncode == 0 and not problems else 1)


if __name__ == "__main__":
    main()
