"""Tests for the C++ vocabulary checker (codec/p2c/check_vocabulary.cpp), driven from Python.

Valid inputs: the frozen P2a vocabulary and the SYNTHETIC fixture test vocabulary (built here with the builder).
Invalid inputs: files derived from those by corruption, written to a temporary directory.
The checker binary is taken from $HASHCODE_P2C_CHECKER or the default build path (target hashcode_p2c_check_vocabulary).
Run: python3 -I tests/p2c/test_check_vocabulary.py
"""
import hashlib
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parents[2]
CHECKER = pathlib.Path(os.environ.get("HASHCODE_P2C_CHECKER",
                                      ROOT / "external/token-vldb2026/build-arm64/hashcode_tools/hashcode_p2c_check_vocabulary"))
P2A = ROOT / "codec/p2a/p2a_vocabulary_v1.bin"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B = load("p2c_builder", ROOT / "codec/p2c/build_vocabulary.py")
F = load("p2c_fixture", ROOT / "tests/p2c/fixtures/make_synthetic_corpus.py")
TMP = tempfile.TemporaryDirectory(prefix="hashcode_p2c_checker_")
D = pathlib.Path(TMP.name)
(D / "fixture.jsonl").write_bytes(F.generate())
RESULT = B.build(D / "fixture.jsonl", "synthetic unit-test fixture (not a real corpus)", allow_unfilled=True)
B.write_outputs(RESULT, D, "fx")


def run(vocab, *extra):
    p = subprocess.run([str(CHECKER), str(vocab), *map(str, extra)], capture_output=True, text=True)
    try:
        out = json.loads(p.stdout)
    except json.JSONDecodeError:
        out = None
    return p.returncode, out, p.stderr


def write(name, blob):
    p = D / name
    p.write_bytes(blob)
    return p


def rebuild(entries, count=None):
    return b"P1V1" + (len(entries) if count is None else count).to_bytes(4, "little") + b"".join(bytes([len(e)]) + e for e in entries)


@unittest.skipUnless(CHECKER.exists(), f"checker not built: {CHECKER}")
class Valid(unittest.TestCase):
    def test_fixture_vocabulary_matches_python_interpretation(self):
        code, out, err = run(D / "fx.bin", "--sha256-file", D / "fx.sha256", "--p2a", P2A, "--heldout-check", D / "fx.heldout_check.tsv")
        self.assertEqual(code, 0, (out, err))
        m = RESULT["manifest"]
        entries = B.read_vocabulary(RESULT["blob"])
        hist = {}
        for e in entries:
            hist[str(len(e))] = hist.get(str(len(e)), 0) + 1
        self.assertEqual((out["entries"], out["file_bytes"], out["sha256"], out["table_id_hex"]),
                         (m["entries"], m["file_bytes"], m["sha256"], m["table_id_hex"]))
        self.assertEqual(out["length_histogram"], hist)
        self.assertEqual((out["learned_hi"], out["learned_kn"]), (m["learned_entries"]["hi"], m["learned_entries"]["kn"]))
        self.assertEqual(out["ascii_entries"], 65536 - 5248 - sum(m["learned_entries"].values()))
        self.assertEqual(out["entry_round_trips"], 65536)
        self.assertGreater(out["heldout_rows_checked"], 0)

    def test_p2a_itself_passes(self):
        code, out, _ = run(P2A, "--p2a", P2A)
        self.assertEqual(code, 0)
        self.assertEqual((out["learned_hi"], out["learned_kn"], out["sha256"][:16]), (0, 0, "c99ff52fa92fa7c8"))


@unittest.skipUnless(CHECKER.exists(), f"checker not built: {CHECKER}")
class Invalid(unittest.TestCase):
    def setUp(self):
        self.entries = B.read_vocabulary(RESULT["blob"])
        self.blob = RESULT["blob"]

    def assert_malformed(self, blob, name):
        code, out, _ = run(write(name, blob))
        self.assertEqual(code, 2, name)
        self.assertFalse(out["ok"])

    def assert_invalid(self, blob, name, *extra, expect=None):
        code, out, _ = run(write(name, blob), *extra)
        self.assertEqual(code, 1, (name, out))
        if expect:
            self.assertTrue(any(expect in f for f in out["failures"]), out["failures"])

    def test_malformed_files_are_rejected_cleanly(self):
        self.assert_malformed(b"", "empty.bin")
        self.assert_malformed(b"P1V2" + self.blob[4:], "magic.bin")
        self.assert_malformed(self.blob[:-1], "truncated.bin")
        self.assert_malformed(self.blob[:100], "short.bin")
        self.assert_malformed(self.blob + b"\x00", "trailing.bin")
        e = list(self.entries)
        e[6000] = e[6001]
        self.assert_malformed(rebuild(e), "duplicate.bin")
        e = list(self.entries)
        e[7] = b"\x08"
        self.assert_malformed(rebuild(e), "singles.bin")
        e = list(self.entries)
        e[6000] = b"x" * 17
        self.assert_malformed(rebuild(e), "too_long.bin")
        self.assert_malformed(rebuild(self.entries, count=65537), "count.bin")
        self.assertEqual(run(D / "does_not_exist.bin")[0], 2)

    def test_validation_failures(self):
        self.assert_invalid(rebuild(self.entries[:-1]), "65535.bin", expect="65536")
        self.assert_invalid(self.blob, "badsha.bin", "--sha256-file", write("bad.sha256", b"0" * 64 + b"  x\n"), expect="SHA-256")
        e = list(self.entries)
        e[300] = "कखग".encode()  # core entry changed (keeps the file well formed)
        self.assert_invalid(rebuild(e), "core.bin", "--p2a", P2A, expect="core")
        e = list(self.entries)
        e[5248] = "कಕ".encode()  # mixed-script learned entry
        self.assert_invalid(rebuild(e), "mixed.bin", "--p2a", P2A, expect="single-script")
        e = list(self.entries)
        n_hi = RESULT["manifest"]["learned_entries"]["hi"]
        e[5248], e[5248 + n_hi] = e[5248 + n_hi], e[5248]  # a Kannada entry before Devanagari ones
        self.assert_invalid(rebuild(e), "order.bin", "--p2a", P2A, expect="after a Kannada")
        e = list(self.entries)
        e[-1], e[-2] = e[-2], e[-1]  # ASCII tail out of P2a order
        self.assert_invalid(rebuild(e), "ascii.bin", "--p2a", P2A, expect="ASCII")
        rows = (D / "fx.heldout_check.tsv").read_text().splitlines()
        cols = rows[1].split("\t")
        cols[2] = str(int(cols[2]) + 1)
        bad = write("bad_check.tsv", ("\n".join([rows[0], "\t".join(cols)] + rows[2:]) + "\n").encode())
        self.assert_invalid(self.blob, "fx_copy.bin", "--heldout-check", bad, expect="disagree")

    def test_usage_errors(self):
        self.assertEqual(subprocess.run([str(CHECKER)], capture_output=True).returncode, 2)
        self.assertEqual(subprocess.run([str(CHECKER), str(P2A), "--bogus", "x"], capture_output=True).returncode, 2)
        self.assertEqual(subprocess.run([str(CHECKER), str(P2A), "--p2a"], capture_output=True).returncode, 2)


def tearDownModule():
    TMP.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=1)
