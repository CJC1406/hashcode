"""Exact-overlap check between P2c training JSONL files and the controlled evaluation datasets (read only).

For every evaluation sample, probes are: the whole sample text, and each of its lines that is at least 32 UTF-8 bytes long.
A probe "occurs" if its JSON string encoding (as written by codec/p2c/convert_wikipedia.py: json.dumps, ensure_ascii=False)
occurs byte for byte inside a training file. Matching is exact: no normalization, no case folding.
Output: counts and sample IDs only (never text). Evaluation data is never modified.
Run: python3 -I codec/p2c/check_eval_overlap.py --train A.jsonl [--train B.jsonl] --out overlap.json [--eval NAME=SAMPLES.jsonl ...]
Without --eval the controlled datasets are checked (SHA-pinned). --eval checks other sample files in the shared schema instead
(their SHA-256 is recorded in the report).
"""
import argparse
import hashlib
import json
import mmap
import pathlib
import sys

sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parents[2]
EVAL = {
    "phase1-kn-hi-v1": ("datasets/phase1/kn_hi_v1.jsonl", "359269f4dbacd71e9442e3a1b38785e603698931fe4e8afa22e51b5ae36bb6fc"),
    "phase1-en-mixed-v1": ("datasets/phase1_en_mixed/en_mixed_v1.jsonl", "6c4685c24ac3603d19ba9121a3c564f88cd3f78542cbc8efec090f7c031d47b0"),
}
MIN_LINE_BYTES = 32


def probes(text):
    out = [text] if text else []
    for line in text.split("\n"):
        if len(line.encode("utf-8")) >= MIN_LINE_BYTES and line != text:
            out.append(line)
    return out


def encode(p):
    return json.dumps(p, ensure_ascii=False)[1:-1].encode("utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--train", required=True, action="append", type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--eval", action="append", default=None, help="NAME=PATH of a sample file in the shared schema")
    args = ap.parse_args(argv)
    if args.eval:
        evals = {}
        for item in args.eval:
            name, path = item.split("=", 1)
            evals[name] = (pathlib.Path(path), None)
    else:
        evals = {name: (ROOT / rel, sha) for name, (rel, sha) in EVAL.items()}
    maps = []
    for t in args.train:
        f = open(t, "rb")
        maps.append((t.name, f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)))
    report = {"method": "exact byte match of JSON-encoded probes; whole sample and lines >= 32 bytes",
              "training_files": [m[0] for m in maps], "datasets": {}}
    for name, (path, sha) in evals.items():
        blob = path.read_bytes()
        digest = hashlib.sha256(blob).hexdigest()
        if sha is not None and digest != sha:
            sys.exit(f"{path} does not match its frozen SHA-256")
        samples = [json.loads(line) for line in blob.decode("utf-8").splitlines() if line.strip()]
        n_probes, hits_whole, hits_line = 0, [], []
        for s in samples:
            text = bytes.fromhex(s["utf8_hex"]).decode("utf-8", errors="surrogateescape")
            ps = probes(text)
            for k, p in enumerate(ps):
                if len(p.encode("utf-8", errors="surrogateescape")) < MIN_LINE_BYTES:
                    continue  # too short to be evidence of copying
                n_probes += 1
                try:
                    needle = encode(p)
                except UnicodeEncodeError:
                    continue  # invalid UTF-8 samples cannot occur in the converter's output
                if any(m.find(needle) >= 0 for _, _, m in maps):
                    (hits_whole if k == 0 else hits_line).append(s["sample_id"])
        report["datasets"][name] = {"samples": len(samples), "sha256": digest, "probes_checked": n_probes,
                                    "samples_found_whole": sorted(set(hits_whole)),
                                    "samples_with_a_line_found": sorted(set(hits_line))}
    for _, f, m in maps:
        m.close()
        f.close()
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: {kk: (len(vv) if isinstance(vv, list) else vv) for kk, vv in v.items()} for k, v in report["datasets"].items()}))


if __name__ == "__main__":
    main()
