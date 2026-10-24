"""D2 evaluation of P1 against the frozen Phase 1 column baselines.

Usage (from the project root):
  python3 -I benchmarks/phase1/evaluate_d2.py --out results/phase1/p1-d2-evaluation \
      --run kn-hi-v1=results/phase1/p1-kn-hi-column-full-1 --frozen kn-hi-v1=results/phase1/column-full-1 \
      --run en-mixed-v1=results/phase1/p1-en-mixed-column-full-1 --frozen en-mixed-v1=results/phase1/en-mixed-column-full-1
D2 (docs/bharat_prototype_experiment.md §6): per evaluation column c, baseline_c = min(sgtt OpenAI200K, sgtt Gemma3) total
stored bytes (Dense, HCC1, vocabulary not charged); reduction_c = (baseline_c - P1_c) / baseline_c * 100; criterion:
median over the declared non-overlapping col-<language>-<category> columns >= 5%, reported per language group.
"""
import argparse
import csv
import json
import pathlib
import statistics
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import run_column_benchmark as rc  # noqa: E402

BASELINES = ["raw_utf8_column", "sgtt_openai200k_column", "sgtt_gemma3_column"]
P1 = "p1_akshara_column"
GROUPS = {"kn-hi-v1": ["hi", "kn"], "en-mixed-v1": ["en", "en-hi", "en-kn"]}
CATEGORIES = {"kn-hi-v1": ["short", "medium", "long", "repeated", "punct_numerals", "mixed", "edge", "tiny"],
              "en-mixed-v1": ["short", "medium", "long", "repeated", "punct_numerals", "structured", "edge", "tiny"]}
THRESHOLD = 5.0


def load(run_dir):
    with open(run_dir / "measurements_column.csv", encoding="utf-8") as f:
        return {(r["column_id"], r["method"]): r for r in csv.DictReader(f)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", required=True, help="DATASET=RUN_DIR (run including P1)")
    ap.add_argument("--frozen", action="append", required=True, help="DATASET=RUN_DIR (frozen baseline run)")
    ap.add_argument("--out", type=pathlib.Path, required=True)
    args = ap.parse_args()
    runs = {k: pathlib.Path(v) for k, v in (a.split("=", 1) for a in args.run)}
    frozen = {k: pathlib.Path(v) for k, v in (a.split("=", 1) for a in args.frozen)}
    args.out.mkdir(parents=True, exist_ok=False)

    problems, rows, groups = [], [], []
    for ds, run_dir in runs.items():
        new, old = load(run_dir), load(frozen[ds])
        # 1. Baselines must be byte-for-byte the frozen ones.
        for key, r in old.items():
            if key not in new:
                problems.append(f"{ds}: {key} missing from new run")
                continue
            for c in rc.DETERMINISTIC:
                if new[key][c] != r[c]:
                    problems.append(f"{ds}: baseline {key} column {c} changed: {r[c]!r} -> {new[key][c]!r}")
        # 2. Per evaluation column.
        for lang in GROUPS[ds]:
            reductions = []
            for cat in CATEGORIES[ds]:
                cid = f"col-{lang}-{cat}"
                t = {m: new[(cid, m)] for m in BASELINES + [P1]}
                if any(x["status"] != "ok" or x["roundtrip_exact"] != "true" for x in t.values()):
                    problems.append(f"{ds}/{cid}: a method is not ok/exact")
                raw, oa, gm, p1 = (int(t[m]["total_stored_bytes"]) for m in BASELINES + [P1])
                base = min(oa, gm)
                red = (base - p1) / base * 100
                reductions.append(red)
                p = t[P1]
                rows.append({"dataset": ds, "language": lang, "category": cat, "column_id": cid, "values": p["value_count"],
                             "original_payload_bytes": p["original_payload_bytes"], "raw_total": raw, "sgtt_openai200k_total": oa,
                             "sgtt_gemma3_total": gm, "baseline_c": base, "baseline_method": "openai200k" if oa < gm else "gemma3" if gm < oa else "tie",
                             "p1_total": p1, "p1_token_ids_bytes": p["encoded_payload_bytes"], "p1_footer_bytes": p["footer_bytes"],
                             "p1_header_plus_boundary_bytes": int(p["header_bytes"]) + int(p["boundary_metadata_bytes"]),
                             "p1_tokens": p["token_count"], "p1_fallback_tokens": p["fallback_tokens"],
                             "reduction_vs_baseline_c_percent": f"{red:.4f}", "p1_vs_raw_percent": f"{(raw - p1) / raw * 100:.4f}",
                             "smallest_method": min([("raw", raw), ("openai200k", oa), ("gemma3", gm), ("p1", p1)], key=lambda x: x[1])[0]})
            med = statistics.median(reductions)
            groups.append({"dataset": ds, "language": lang, "columns": len(reductions), "median_reduction_percent": f"{med:.4f}",
                           "min_reduction_percent": f"{min(reductions):.4f}", "max_reduction_percent": f"{max(reductions):.4f}",
                           "columns_with_reduction_ge_5": sum(r >= THRESHOLD for r in reductions), "d2_met": med >= THRESHOLD})
        # 3. Grouped (overlapping) language columns, for context only.
        for lang in GROUPS[ds]:
            cid = f"col-{lang}-all"
            t = {m: new[(cid, m)] for m in BASELINES + [P1]}
            orig = int(t[P1]["original_payload_bytes"])
            raw, p1 = int(t["raw_utf8_column"]["total_stored_bytes"]), int(t[P1]["total_stored_bytes"])
            base = min(int(t["sgtt_openai200k_column"]["total_stored_bytes"]), int(t["sgtt_gemma3_column"]["total_stored_bytes"]))
            vocab = int(t[P1]["shared_vocabulary_bytes"])
            saving = (raw - p1) / orig
            groups.append({"dataset": ds, "language": lang, "context_column": cid, "raw_total": raw, "best_sgtt_total": base, "p1_total": p1,
                           "p1_vs_best_sgtt_percent": f"{(base - p1) / base * 100:.4f}", "p1_shared_vocabulary_bytes": vocab,
                           "p1_break_even_original_bytes_vs_raw": f"{vocab / saving:.0f}" if saving > 0 else "never"})

    rc.pv.write_csv(args.out / "d2_per_column.csv", rows)
    with open(args.out / "d2_summary.json", "w") as f:
        json.dump({"threshold_percent": THRESHOLD, "runs": {k: str(v) for k, v in runs.items()}, "frozen": {k: str(v) for k, v in frozen.items()},
                   "baseline_integrity_problems": problems, "groups": groups}, f, indent=2)
    print(f"baseline integrity problems: {len(problems)}")
    for p in problems[:10]:
        print("  " + p)
    for g in groups:
        print(json.dumps(g))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
