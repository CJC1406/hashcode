"""Independent audit of a column-mode run directory (no re-run of the benchmark).

Usage: python3 -I benchmarks/phase1/audit_column_results.py results/phase1/<column run>
Re-checks, from measurements_column.csv, containers.tsv, decoded_values.tsv and the frozen dataset:
identical ordered inputs across methods, exact per-value reconstruction, byte accounting against the
serialized container, ratio formulas, vocabulary disclosure, Dense token-ID width rule, timing fields,
and lists every column where an sgtt method stores more bytes than raw UTF-8.
"""
import csv
import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SGTT = ["sgtt_openai200k_column", "sgtt_gemma3_column"]
P1 = ["p1_akshara_column", "p2a_space_akshara_column"]  # fixed u16 token IDs


def varint(buf, pos):
    v, shift = 0, 0
    while True:
        b = buf[pos]
        pos += 1
        v |= (b & 0x7F) << shift
        if not b & 0x80:
            return v, pos
        shift += 7


def seq_fnv(values):
    h = 0xcbf29ce484222325
    for v in values:
        for b in len(v).to_bytes(8, "little") + v:
            h = ((h ^ b) * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def main(run_dir: pathlib.Path):
    meta = json.loads((run_dir / "run_metadata.json").read_text())
    dataset = {json.loads(l)["sample_id"]: bytes.fromhex(json.loads(l)["utf8_hex"])
               for l in (ROOT / meta["dataset"]["path"]).read_text(encoding="utf-8").splitlines()}
    rows = list(csv.DictReader(open(run_dir / "measurements_column.csv", encoding="utf-8")))
    containers = {(r["column_id"], r["method"]): bytes.fromhex(r["container_hex"]) for r in csv.DictReader(open(run_dir / "containers.tsv", encoding="utf-8"), delimiter="\t")}
    decoded = {}
    for r in csv.DictReader(open(run_dir / "decoded_values.tsv", encoding="utf-8"), delimiter="\t"):
        decoded.setdefault((r["column_id"], r["method"]), []).append(bytes.fromhex(r["decoded_hex"]))
    by = {(r["column_id"], r["method"]): r for r in rows}
    problems, notes = [], []
    METHODS = sorted({r["method"] for r in rows}, key=lambda m: (m != "raw_utf8_column", m))
    codecs = [m for m in METHODS if m != "raw_utf8_column"]

    for cid, members in meta["columns"].items():
        values = [dataset[s] for s in members]
        fps = {by[(cid, m)]["input_sequence_fnv1a64"] for m in METHODS}
        if fps != {str(seq_fnv(values))}:
            problems.append(f"{cid}: methods did not receive the identical ordered sequence")
        for m in METHODS:
            r = by[(cid, m)]
            if r["status"] != "ok":
                problems.append(f"{cid}/{m}: status {r['status']}")
                continue
            if decoded.get((cid, m), []) != values:
                problems.append(f"{cid}/{m}: decoded values differ (order, boundaries or bytes)")
            buf = containers[(cid, m)]
            parts = sum(int(r[k]) for k in ("header_bytes", "boundary_metadata_bytes", "encoded_payload_bytes", "bitmap_bytes", "footer_bytes"))
            if not (parts == int(r["total_stored_bytes"]) == len(buf)):
                problems.append(f"{cid}/{m}: components {parts}, total {r['total_stored_bytes']}, container {len(buf)}")
            pos = 6
            n, pos = varint(buf, pos)
            lengths = []
            for _ in range(n):
                l, pos = varint(buf, pos)
                lengths.append(l)
            blob_len, pos = varint(buf, pos)
            if lengths != [len(v) for v in values] or blob_len != len(buf) - pos or pos - 6 != int(r["boundary_metadata_bytes"]):
                problems.append(f"{cid}/{m}: container length table / boundary bytes")
            orig, total = int(r["original_payload_bytes"]), int(r["total_stored_bytes"])
            exp_ratio = f"{orig / total:.6f}" if orig else ""
            exp_red = f"{(orig - total) / orig * 100:.4f}" if orig else ""
            if r["compression_ratio"] != exp_ratio or r["size_reduction_percent"] != exp_red:
                problems.append(f"{cid}/{m}: ratio fields inconsistent with original/total")
            if m == "raw_utf8_column":
                if r["shared_vocabulary_bytes"] != "0" or int(r["bitmap_bytes"]) or int(r["footer_bytes"]):
                    problems.append(f"{cid}/raw: unexpected vocabulary/bitmap/footer")
            else:
                if int(r["shared_vocabulary_bytes"]) <= 0 or not r["total_stored_bytes_oneshot_with_vocabulary"]:
                    problems.append(f"{cid}/{m}: shared vocabulary not disclosed")
                if r["token_count"]:
                    used, width = int(r["used_tokens"]), int(r["token_id_bytes"])
                    want = 2 if m in P1 else 1 if used <= 256 else 2 if used <= 65536 else 4  # P1: fixed u16 IDs; sgtt Dense: by distinct count
                    if width != want:
                        problems.append(f"{cid}/{m}: token_id_bytes {width} but used_tokens {used} implies {want}")
                    if int(r["encoded_payload_bytes"]) != int(r["token_count"]) * width:
                        problems.append(f"{cid}/{m}: token IDs != count x width")
                if orig and not (r["codec_init_ms_median"] and r["column_encode_ms_median"] and r["decoder_init_ms_median"] and r["column_decode_ms_median"]):
                    problems.append(f"{cid}/{m}: missing separated timing fields")

    expansions = []
    for cid in meta["columns"]:
        raw = int(by[(cid, "raw_utf8_column")]["total_stored_bytes"])
        for m in codecs:
            t = int(by[(cid, m)]["total_stored_bytes"])
            if int(by[(cid, m)]["original_payload_bytes"]) and t >= raw:
                expansions.append(f"{cid}/{m}: {t} >= raw {raw}")
    ratios = [float(r["compression_ratio"]) for r in rows if r["method"] in SGTT and r["compression_ratio"]]
    widths = {}
    for r in rows:
        if r["method"] in SGTT and r["token_id_bytes"]:
            widths.setdefault(r["token_id_bytes"], []).append(r["column_id"])
    print(f"audited {len(rows)} rows, {len(meta['columns'])} columns: {len(problems)} problems")
    for p in problems:
        print("  PROBLEM " + p)
    print(f"columns where a codec method is not smaller than raw HCC1 ({len(expansions)}):")
    for e in expansions:
        print("  " + e)
    print(f"sgtt per-column ratios (n={len(ratios)}): median {statistics.median(ratios):.3f}, min {min(ratios):.3f}, max {max(ratios):.3f}")
    print("Dense token-ID width by column: " + "; ".join(f"{w} B: {len(c)} rows" for w, c in sorted(widths.items())))
    nul = sum(b"\x00" in v for v in dataset.values())
    lf = sum(b"\n" in v for v in dataset.values())
    cr = sum(b"\r" in v for v in dataset.values())
    print(f"dataset values containing NUL: {nul}, LF: {lf}, CR: {cr}"
          + ("" if nul else "; NUL handling is covered by hashcode_column_tests, not by this run")
          + ("" if lf else "; LF handling is covered by hashcode_column_tests, not by this run"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(pathlib.Path(sys.argv[1])))
