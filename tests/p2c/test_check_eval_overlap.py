"""Test for codec/p2c/check_eval_overlap.py: a planted evaluation sample in a temporary training file must be found.

The temporary file lives in a temporary directory and is deleted; evaluation data is only read.
Run: python3 -I tests/p2c/test_check_eval_overlap.py
"""
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("p2c_overlap", ROOT / "codec" / "p2c" / "check_eval_overlap.py")
O = importlib.util.module_from_spec(spec)
spec.loader.exec_module(O)


class Overlap(unittest.TestCase):
    def test_planted_sample_is_found_and_clean_file_is_not(self):
        samples = [json.loads(l) for l in (ROOT / "datasets/phase1/kn_hi_v1.jsonl").read_text(encoding="utf-8").splitlines()]
        target = next(s for s in samples if len(bytes.fromhex(s["utf8_hex"])) >= 64 and b"\n" not in bytes.fromhex(s["utf8_hex"]))
        text = bytes.fromhex(target["utf8_hex"]).decode("utf-8")
        with tempfile.TemporaryDirectory() as d:
            planted, clean, out = pathlib.Path(d) / "p.jsonl", pathlib.Path(d) / "c.jsonl", pathlib.Path(d) / "o.json"
            planted.write_text(json.dumps({"doc_id": "x:1", "text": "पहले\n" + text + "\nबाद"}, ensure_ascii=False) + "\n", encoding="utf-8")
            clean.write_text(json.dumps({"doc_id": "x:2", "text": "असंबंधित पाठ"}, ensure_ascii=False) + "\n", encoding="utf-8")
            O.main(["--train", str(planted), "--out", str(out)])
            r = json.loads(out.read_text())["datasets"]["phase1-kn-hi-v1"]
            self.assertIn(target["sample_id"], r["samples_found_whole"])
            O.main(["--train", str(clean), "--out", str(out)])
            r = json.loads(out.read_text())["datasets"]
            self.assertTrue(all(not v["samples_found_whole"] and not v["samples_with_a_line_found"] for v in r.values()))

    def test_probes(self):
        self.assertEqual(O.probes(""), [])
        self.assertEqual(O.probes("short"), ["short"])
        long_line = "क" * 11  # 33 bytes
        self.assertEqual(O.probes("a\n" + long_line), ["a\n" + long_line, long_line])


if __name__ == "__main__":
    unittest.main(verbosity=1)
