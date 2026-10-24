"""Phase 2 exploratory evaluation of P2a (space+akshara) against frozen raw, sgtt and P1 on the controlled datasets.

Usage (from the project root):
  python3 -I benchmarks/phase2/evaluate_p2a.py --out results/phase2/p2a-evaluation \
      --run kn-hi-v1=results/phase2/p2a-kn-hi-column-full-1 --run en-mixed-v1=results/phase2/p2a-en-mixed-column-full-1
Checks first that raw and both sgtt baselines equal the frozen Phase 1 runs and P1 equals the frozen P1 runs on all
non-timing columns. Primary metric (docs/phase2_proposal.md §5): byte-weighted total stored bytes per language group over
the 8 non-overlapping col-<language>-<category> columns, against the per-column best sgtt baseline.
These datasets are controlled harness-validation data: results are exploratory and cannot satisfy the real-data criterion.
"""
import argparse
import csv
import json
import pathlib
import statistics
import sys

sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "benchmarks" / "phase1"))
import run_column_benchmark as rc  # noqa: E402

FROZEN = {"kn-hi-v1": {"baselines": "results/phase1/column-full-1", "p1": "results/phase1/p1-kn-hi-column-full-1"},
          "en-mixed-v1": {"baselines": "results/phase1/en-mixed-column-full-1", "p1": "results/phase1/p1-en-mixed-column-full-1"}}
GROUPS = {"kn-hi-v1": ["hi", "kn"], "en-mixed-v1": ["en", "en-hi", "en-kn"]}
CATEGORIES = {"kn-hi-v1": ["short", "medium", "long", "repeated", "punct_numerals", "mixed", "edge", "tiny"],
              "en-mixed-v1": ["short", "medium", "long", "repeated", "punct_numerals", "structured", "edge", "tiny"]}
RAW, OA, GM, P1, P2A = "raw_utf8_column", "sgtt_openai200k_column", "sgtt_gemma3_column", "p1_akshara_column", "p2a_space_akshara_column"
THRESHOLD = 5.0


def load(run_dir):
    with open(ROOT / run_dir / "measurements_column.csv", encoding="utf-8") as f:
        return {(r["column_id"], r["method"]): r for r in csv.DictReader(f)}


def pct(base, cand):
    return (base - cand) / base * 100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", required=True, help="DATASET=RUN_DIR (run including P2a)")
    ap.add_argument("--out", type=pathlib.Path, required=True)
    args = ap.parse_args()
    runs = dict(a.split("=", 1) for a in args.run)
    args.out.mkdir(parents=True, exist_ok=False)
    problems, per_column, groups = [], [], []

    for ds, run_dir in runs.items():
        new = load(run_dir)
        for label, frozen_dir, methods in (("baseline", FROZEN[ds]["baselines"], [RAW, OA, GM]), ("p1", FROZEN[ds]["p1"], [P1])):
            old = load(frozen_dir)
            for key, r in old.items():
                if key[1] not in methods:
                    continue
                for c in rc.DETERMINISTIC:
                    if new[key][c] != r[c]:
                        problems.append(f"{ds}: frozen {label} {key} column {c}: {r[c]!r} -> {new[key][c]!r}")
        for lang in GROUPS[ds]:
            sums = {k: 0 for k in ("original", "raw", "baseline", "p1", "p2a", "p1_ids", "p2a_ids", "baseline_ids", "p1_tokens", "p2a_tokens", "p1_fallback", "p2a_fallback")}
            red_p1, red_p2a = [], []
            for cat in CATEGORIES[ds]:
                cid = f"col-{lang}-{cat}"
                t = {m: new[(cid, m)] for m in (RAW, OA, GM, P1, P2A)}
                if any(x["status"] != "ok" or x["roundtrip_exact"] != "true" for x in t.values()):
                    problems.append(f"{ds}/{cid}: a method is not ok/exact")
                tot = {m: int(t[m]["total_stored_bytes"]) for m in t}
                best = OA if tot[OA] <= tot[GM] else GM
                base = tot[best]
                red_p1.append(pct(base, tot[P1]))
                red_p2a.append(pct(base, tot[P2A]))
                sums["original"] += int(t[RAW]["original_payload_bytes"])
                sums["raw"] += tot[RAW]
                sums["baseline"] += base
                sums["p1"] += tot[P1]
                sums["p2a"] += tot[P2A]
                sums["baseline_ids"] += int(t[best]["encoded_payload_bytes"])
                for name, m in (("p1", P1), ("p2a", P2A)):
                    sums[f"{name}_ids"] += int(t[m]["encoded_payload_bytes"])
                    sums[f"{name}_tokens"] += int(t[m]["token_count"] or 0)
                    sums[f"{name}_fallback"] += int(t[m]["fallback_tokens"] or 0)
                per_column.append({"dataset": ds, "language": lang, "category": cat, "column_id": cid,
                                   "original_payload_bytes": t[RAW]["original_payload_bytes"], "raw_total": tot[RAW], "baseline_c": base,
                                   "baseline_method": best, "p1_total": tot[P1], "p2a_total": tot[P2A],
                                   "p1_token_id_bytes": t[P1]["encoded_payload_bytes"], "p2a_token_id_bytes": t[P2A]["encoded_payload_bytes"],
                                   "baseline_token_id_bytes": t[best]["encoded_payload_bytes"],
                                   "p1_fallback_tokens": t[P1]["fallback_tokens"], "p2a_fallback_tokens": t[P2A]["fallback_tokens"],
                                   "p2a_vs_baseline_c_percent": f"{pct(base, tot[P2A]):.4f}", "p2a_vs_p1_percent": f"{pct(tot[P1], tot[P2A]):.4f}",
                                   "p2a_vs_raw_percent": f"{pct(tot[RAW], tot[P2A]):.4f}"})
            groups.append({
                "dataset": ds, "language": lang, "columns": len(red_p2a), **sums,
                "byte_weighted_p2a_vs_baseline_percent": f"{pct(sums['baseline'], sums['p2a']):.4f}",
                "byte_weighted_p1_vs_baseline_percent": f"{pct(sums['baseline'], sums['p1']):.4f}",
                "byte_weighted_p2a_vs_p1_percent": f"{pct(sums['p1'], sums['p2a']):.4f}",
                "byte_weighted_p2a_vs_raw_percent": f"{pct(sums['raw'], sums['p2a']):.4f}",
                "payload_only_p2a_vs_baseline_percent": f"{pct(sums['baseline_ids'], sums['p2a_ids']):.4f}",
                "median_p2a_vs_baseline_percent": f"{statistics.median(red_p2a):.4f}",
                "median_p1_vs_baseline_percent": f"{statistics.median(red_p1):.4f}",
                "fallback_share_p1": f"{sums['p1_fallback'] / sums['p1_tokens']:.4f}",
                "fallback_share_p2a": f"{sums['p2a_fallback'] / sums['p2a_tokens']:.4f}",
                "byte_weighted_5pct_vs_baseline_met": pct(sums["baseline"], sums["p2a"]) >= THRESHOLD,
            })

    vocab = {name: (ROOT / path).stat().st_size for name, path in (("p1", rc.P1_VOCABULARY), ("p2a", rc.P2A_VOCABULARY))}
    rc.pv.write_csv(args.out / "p2a_per_column.csv", per_column)
    rc.pv.write_csv(args.out / "p2a_groups.csv", groups)
    summary = {"data_status": "controlled harness-validation datasets only; exploratory; cannot satisfy the Phase 2 real-data criterion",
               "runs": runs, "frozen": FROZEN, "frozen_integrity_problems": problems, "shared_vocabulary_bytes": vocab,
               "sgtt_shared_vocabulary_bytes": {"openai200k": 3332170, "gemma3": 4275024}, "groups": groups}
    (args.out / "p2a_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"frozen integrity problems: {len(problems)}")
    for p in problems[:10]:
        print("  " + p)
    for g in groups:
        print(f"{g['language']:6} bytes: raw {g['raw']:6} best-sgtt {g['baseline']:6} P1 {g['p1']:6} P2a {g['p2a']:6} | "
              f"P2a vs sgtt {g['byte_weighted_p2a_vs_baseline_percent']:>9}% vs P1 {g['byte_weighted_p2a_vs_p1_percent']:>8}% | "
              f"median vs sgtt P2a {g['median_p2a_vs_baseline_percent']:>8}% (P1 {g['median_p1_vs_baseline_percent']:>8}%) | "
              f"fallback P1 {g['fallback_share_p1']} -> P2a {g['fallback_share_p2a']}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
