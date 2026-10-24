"""Phase 2 exploratory evaluation of P2b (per-column ID width) against frozen raw, sgtt, P1 and P2a on the controlled data.

Usage (from the project root):
  python3 -I benchmarks/phase2/evaluate_p2b.py --out results/phase2/p2b-evaluation \
      --run kn-hi-v1=results/phase2/p2b-kn-hi-column-full-1 --run en-mixed-v1=results/phase2/p2b-en-mixed-column-full-1
Integrity first: raw and both sgtt rows must equal the frozen Phase 1 runs, P1 the frozen P1 runs, P2a the frozen P2a runs,
on all non-timing columns. Primary metric: byte-weighted total stored bytes over the 8 non-overlapping col-<language>-<category>
columns per group (and all 40), against the per-column best sgtt baseline. Shared vocabularies are reported, never charged.
Controlled harness-validation data only: exploratory; it cannot satisfy the Phase 2 real-data criterion.
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

RAW, OA, GM, P1, P2A, P2B = ("raw_utf8_column", "sgtt_openai200k_column", "sgtt_gemma3_column", "p1_akshara_column",
                             "p2a_space_akshara_column", "p2b_column_id_width")
FROZEN = {"kn-hi-v1": [("results/phase1/column-full-1", [RAW, OA, GM]), ("results/phase1/p1-kn-hi-column-full-1", [P1]),
                       ("results/phase2/p2a-kn-hi-column-full-1", [P2A])],
          "en-mixed-v1": [("results/phase1/en-mixed-column-full-1", [RAW, OA, GM]), ("results/phase1/p1-en-mixed-column-full-1", [P1]),
                          ("results/phase2/p2a-en-mixed-column-full-1", [P2A])]}
GROUPS = {"kn-hi-v1": ["hi", "kn"], "en-mixed-v1": ["en", "en-hi", "en-kn"]}
CATEGORIES = {"kn-hi-v1": ["short", "medium", "long", "repeated", "punct_numerals", "mixed", "edge", "tiny"],
              "en-mixed-v1": ["short", "medium", "long", "repeated", "punct_numerals", "structured", "edge", "tiny"]}
CANDIDATES = {"p1": P1, "p2a": P2A, "p2b": P2B}
THRESHOLD = 5.0


def load(run_dir):
    with open(ROOT / run_dir / "measurements_column.csv", encoding="utf-8") as f:
        return {(r["column_id"], r["method"]): r for r in csv.DictReader(f)}


def pct(base, cand):
    return (base - cand) / base * 100 if base else 0.0


def blank_totals():
    t = {"columns": 0, "original": 0, "raw": 0, "baseline": 0, "baseline_payload": 0}
    for c in CANDIDATES:
        t.update({f"{c}_total": 0, f"{c}_payload": 0, f"{c}_metadata": 0, f"{c}_fixed": 0, f"{c}_tokens": 0, f"{c}_fallback": 0})
    t.update({"p2b_width1_columns": 0, "p2b_width2_columns": 0})
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", required=True, help="DATASET=RUN_DIR (run including P2b)")
    ap.add_argument("--out", type=pathlib.Path, required=True)
    args = ap.parse_args()
    runs = dict(a.split("=", 1) for a in args.run)
    args.out.mkdir(parents=True, exist_ok=False)
    problems, per_column, groups = [], [], []
    overall = blank_totals()
    medians_all = {c: [] for c in CANDIDATES}

    for ds, run_dir in runs.items():
        new = load(run_dir)
        for frozen_dir, methods in FROZEN[ds]:
            old = load(frozen_dir)
            for key, r in old.items():
                if key[1] in methods:
                    for c in rc.DETERMINISTIC:
                        if new[key][c] != r[c]:
                            problems.append(f"{ds}: frozen {key} ({frozen_dir}) column {c}: {r[c]!r} -> {new[key][c]!r}")
        for lang in GROUPS[ds]:
            g = blank_totals()
            reds = {c: [] for c in CANDIDATES}
            for cat in CATEGORIES[ds]:
                cid = f"col-{lang}-{cat}"
                t = {m: new[(cid, m)] for m in (RAW, OA, GM, P1, P2A, P2B)}
                if any(x["status"] != "ok" or x["roundtrip_exact"] != "true" for x in t.values()):
                    problems.append(f"{ds}/{cid}: a method is not ok/exact")
                tot = {m: int(t[m]["total_stored_bytes"]) for m in t}
                best = OA if tot[OA] <= tot[GM] else GM
                row = {"dataset": ds, "language": lang, "category": cat, "column_id": cid, "original_payload_bytes": t[RAW]["original_payload_bytes"],
                       "raw_total": tot[RAW], "baseline_method": best, "baseline_c": tot[best], "baseline_token_bytes": t[best]["encoded_payload_bytes"]}
                for acc in (g, overall):
                    acc["columns"] += 1
                    acc["original"] += int(t[RAW]["original_payload_bytes"])
                    acc["raw"] += tot[RAW]
                    acc["baseline"] += tot[best]
                    acc["baseline_payload"] += int(t[best]["encoded_payload_bytes"])
                for c, m in CANDIDATES.items():
                    x = t[m]
                    fixed = int(x["header_bytes"]) + int(x["boundary_metadata_bytes"]) + int(x["footer_bytes"])
                    for acc in (g, overall):
                        acc[f"{c}_total"] += tot[m]
                        acc[f"{c}_payload"] += int(x["encoded_payload_bytes"])
                        acc[f"{c}_metadata"] += int(x["bitmap_bytes"])
                        acc[f"{c}_fixed"] += fixed
                        acc[f"{c}_tokens"] += int(x["token_count"] or 0)
                        acc[f"{c}_fallback"] += int(x["fallback_tokens"] or 0)
                    reds[c].append(pct(tot[best], tot[m]))
                    medians_all[c].append(pct(tot[best], tot[m]))
                    row.update({f"{c}_total": tot[m], f"{c}_token_bytes": x["encoded_payload_bytes"], f"{c}_metadata_bytes": x["bitmap_bytes"],
                                f"{c}_vs_baseline_c_percent": f"{pct(tot[best], tot[m]):.4f}"})
                width = t[P2B]["token_id_bytes"]
                row.update({"p2b_id_width": width, "p2b_distinct_tokens": t[P2B]["used_tokens"], "p2b_mapping_bytes": t[P2B]["mapping_bytes"],
                            "p2b_vs_p2a_percent": f"{pct(tot[P2A], tot[P2B]):.4f}"})
                for acc in (g, overall):
                    if width == "1":
                        acc["p2b_width1_columns"] += 1
                    elif width == "2":
                        acc["p2b_width2_columns"] += 1
                per_column.append(row)
            groups.append(summarize(ds, lang, g, reds))
    groups.append(summarize("all", "all-40", overall, medians_all))

    vocab = {"p1": (ROOT / rc.P1_VOCABULARY).stat().st_size, "p2a_and_p2b": (ROOT / rc.P2A_VOCABULARY).stat().st_size,
             "sgtt_openai200k": 3332170, "sgtt_gemma3": 4275024}
    rc.pv.write_csv(args.out / "p2b_per_column.csv", per_column)
    rc.pv.write_csv(args.out / "p2b_groups.csv", groups)
    (args.out / "p2b_summary.json").write_text(json.dumps({
        "data_status": "controlled harness-validation datasets only; exploratory; cannot satisfy the Phase 2 real-data criterion",
        "runs": runs, "frozen": FROZEN, "frozen_integrity_problems": problems, "shared_vocabulary_bytes": vocab,
        "vocabulary_amortization": "shared static assets, not charged per column; reported separately", "groups": groups}, indent=2) + "\n")
    print(f"frozen integrity problems: {len(problems)}")
    for p in problems[:10]:
        print("  " + p)
    for g in groups:
        print(f"{g['group']:7} sgtt {g['baseline']:6} P1 {g['p1_total']:6} P2a {g['p2a_total']:6} P2b {g['p2b_total']:6} | P2b vs sgtt {g['p2b_vs_baseline_bytes_percent']:>8}% "
              f"vs P2a {g['p2b_vs_p2a_bytes_percent']:>7}% | P2b payload {g['p2b_payload']:6} mapping {g['p2b_metadata']:5} fixed {g['p2b_fixed']:5} | "
              f"median P2b {g['median_p2b_vs_baseline_percent']:>7}% | widths 1B/2B {g['p2b_width1_columns']}/{g['p2b_width2_columns']}")
    return 1 if problems else 0


def summarize(ds, lang, t, reds):
    out = {"dataset": ds, "group": lang, **t}
    for c in CANDIDATES:
        out[f"{c}_vs_baseline_bytes_percent"] = f"{pct(t['baseline'], t[f'{c}_total']):.4f}"
        out[f"{c}_payload_vs_baseline_payload_percent"] = f"{pct(t['baseline_payload'], t[f'{c}_payload']):.4f}"
        out[f"median_{c}_vs_baseline_percent"] = f"{statistics.median(reds[c]):.4f}"
        out[f"{c}_fallback_share"] = f"{t[f'{c}_fallback'] / t[f'{c}_tokens']:.4f}" if t[f"{c}_tokens"] else ""
    out["p2b_vs_p2a_bytes_percent"] = f"{pct(t['p2a_total'], t['p2b_total']):.4f}"
    out["p2b_vs_raw_bytes_percent"] = f"{pct(t['raw'], t['p2b_total']):.4f}"
    out["p2b_beats_p2a_by_total_bytes"] = t["p2b_total"] < t["p2a_total"]
    out["p2b_beats_sgtt_by_total_bytes"] = t["p2b_total"] < t["baseline"]
    out["p2b_5pct_byte_weighted_vs_sgtt"] = pct(t["baseline"], t["p2b_total"]) >= THRESHOLD
    return out


if __name__ == "__main__":
    sys.exit(main())
