"""Unit tests for codec/p2c/build_vocabulary.py, using ONLY the synthetic fixture (tests/p2c/fixtures/) and tiny inline strings.

The fixture is meaningless pseudo-word text, not a corpus; nothing here measures compression effectiveness.
Run: python3 -I tests/p2c/test_build_vocabulary.py
"""
import hashlib
import importlib.util
import json
import pathlib
import random
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from fractions import Fraction

sys.dont_write_bytecode = True  # importing the P1/P2c builders must not leave __pycache__ in the repository

ROOT = pathlib.Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B = load("p2c_builder", ROOT / "codec" / "p2c" / "build_vocabulary.py")
F = load("p2c_fixture", ROOT / "tests" / "p2c" / "fixtures" / "make_synthetic_corpus.py")
LABEL = "synthetic unit-test fixture (not a real corpus)"
# Golden checksum of the TEST vocabulary built from the synthetic fixture with the default L candidates and --allow-unfilled
# (the fixture cannot fill L/2 = 2,048 entries per language, so all four L tie -> 4,096). Builder v2 rules.
GOLDEN_FIXTURE_VOCAB_SHA256 = "39e4ac841f4f958f2a2500ab4df8c8adeb58cedb969dbf423bea20a475a20b37"

TMP = tempfile.TemporaryDirectory(prefix="hashcode_p2c_test_")
FIXTURE = pathlib.Path(TMP.name) / "synthetic_fixture.jsonl"
FIXTURE.write_bytes(F.generate())
P2A = B.load_p2a()
SEG = B.Segmenter()
_BUILD = {}


def fixture_build():
    if "r" not in _BUILD:
        _BUILD["r"] = B.build(FIXTURE, LABEL, allow_unfilled=True)
    return _BUILD["r"]


def corpus(tmpdir, docs, name="c.jsonl"):
    p = pathlib.Path(tmpdir) / name
    p.write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in docs), encoding="utf-8")
    return p


class Fixture(unittest.TestCase):
    def test_generator_is_deterministic_and_pinned(self):
        a, b = F.generate(), F.generate()
        self.assertEqual(a, b)
        self.assertEqual(hashlib.sha256(a).hexdigest(), F.PINNED_SHA256)

    def test_fixture_is_not_an_evaluation_dataset(self):
        self.assertNotIn(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(), B.FORBIDDEN_CORPUS_SHA256)


class Determinism(unittest.TestCase):
    def test_two_builds_identical_and_golden(self):
        r1, r2 = B.build(FIXTURE, LABEL, allow_unfilled=True), B.build(FIXTURE, LABEL, allow_unfilled=True)
        self.assertEqual(r1["blob"], r2["blob"])
        self.assertEqual(r1["manifest"], r2["manifest"])
        self.assertEqual(r1["manifest"]["sha256"], GOLDEN_FIXTURE_VOCAB_SHA256)
        self.assertEqual(r1["manifest"]["table_id_hex"], hashlib.sha256(r1["blob"]).hexdigest()[:16])

    def test_cli_outputs_match_library(self):
        with tempfile.TemporaryDirectory() as d:
            for k in (1, 2):
                subprocess.run([sys.executable, "-I", str(ROOT / "codec/p2c/build_vocabulary.py"), "--corpus", str(FIXTURE),
                                "--corpus-label", LABEL, "--out-dir", f"{d}/b{k}", "--allow-unfilled"], check=True, capture_output=True)
            b1, b2 = (pathlib.Path(d) / f"b{k}/p2c_vocabulary.bin" for k in (1, 2))
            self.assertEqual(b1.read_bytes(), b2.read_bytes())
            self.assertEqual(b1.read_bytes(), fixture_build()["blob"])
            sha_line = (pathlib.Path(d) / "b1/p2c_vocabulary.sha256").read_text()
            self.assertEqual(sha_line, f"{GOLDEN_FIXTURE_VOCAB_SHA256}  p2c_vocabulary.bin\n")

    def test_l_zero_reproduces_p2a_exactly(self):
        r = B.build(FIXTURE, LABEL, fixed_l=0)
        self.assertEqual(r["manifest"]["sha256"], B.P2A_SHA256)


class Layout(unittest.TestCase):
    def test_invariants(self):
        r = fixture_build()
        e, m = r["entries"], r["manifest"]
        self.assertEqual(len(e), 65536)
        self.assertEqual(len(set(e)), 65536)
        self.assertEqual(e[:B.CORE_ENTRIES], P2A[:B.CORE_ENTRIES])
        self.assertEqual(B.read_vocabulary(r["blob"]), e)
        n = sum(m["learned_entries"].values())
        lo, hi = m["id_ranges"]["learned_hi"]
        self.assertEqual((lo, hi), (5248, 5248 + m["learned_entries"]["hi"] - 1))
        learned = e[B.CORE_ENTRIES:B.CORE_ENTRIES + n]
        self.assertEqual(e[B.CORE_ENTRIES + n:], P2A[B.CORE_ENTRIES:B.CORE_ENTRIES + 65536 - B.CORE_ENTRIES - n])
        self.assertEqual(m["learned_slots_returned_to_ascii"], m["L_selected"] - n)
        p2a = set(P2A)
        for i, t in enumerate(learned):
            self.assertLessEqual(len(t), 16)
            self.assertNotIn(t, p2a)
            text = t.decode("utf-8")
            body = text[1:] if text.startswith(" ") else text
            self.assertNotIn(" ", body)
            langs = {SEG.script_of(c) for c in body if c not in B.ZW}
            self.assertEqual(len(langs), 1)
            self.assertEqual(langs.pop(), "hi" if i < m["learned_entries"]["hi"] else "kn")
            ak = SEG.aksharas(body)
            self.assertEqual("".join(ak), body)
            self.assertTrue(1 <= len(ak) <= 5, (t, ak))  # 16 bytes / 3-byte code points
            self.assertNotIn(body[0], SEG.signs | SEG.nukta | set(B.ZW))  # starts on an akshara boundary

    def test_learned_order_is_rank_order(self):
        r = fixture_build()
        m = r["manifest"]
        hi = r["entries"][B.CORE_ENTRIES:B.CORE_ENTRIES + m["learned_entries"]["hi"]]
        self.assertEqual(hi, [x[0] for x in r["ranked"]["hi"][:len(hi)]])

    def test_quotas_never_transfer(self):
        # D2: hi has 10 candidates, kn has 100; at L = 40 each quota is 20. kn must NOT take hi's 10 unused slots.
        hi = [("क".encode() + bytes([0xE0, 0xA5, 0xA6 + i]), 1, 2, 1) for i in range(10)]   # क + Devanagari digit
        kn = [("ಕ".encode() + bytes([0xE0, 0xB3, 0xA6 + i % 10]) + "ಕ".encode() * (i // 10), 1, 2, 1) for i in range(100)]
        entries, filled = B.assemble(P2A, {"hi": hi, "kn": kn}, 40)
        self.assertEqual(filled, {"hi": 10, "kn": 20})
        self.assertEqual(entries[B.CORE_ENTRIES + 10:B.CORE_ENTRIES + 30], [k[0] for k in kn[:20]])
        self.assertEqual(entries[B.CORE_ENTRIES + 30], P2A[B.CORE_ENTRIES])  # the 10 unused slots went back to ASCII
        self.assertFalse(B.eligible({"hi": hi, "kn": kn}, 40))  # D1: so L = 40 is not eligible for selection
        self.assertTrue(B.eligible({"hi": hi, "kn": kn}, 20))

    def test_capacity_limits(self):
        r = fixture_build()
        for bad in (-2, 3, 65536 - B.CORE_ENTRIES + 2):
            with self.assertRaises(B.BuildError):
                B.assemble(P2A, r["ranked"], bad)
        entries, _ = B.assemble(P2A, r["ranked"], 65536 - B.CORE_ENTRIES)  # largest valid L: all slots learned or returned
        self.assertEqual(len(entries), 65536)

    def test_check_vocabulary_rejects_bad_tables(self):
        r = fixture_build()
        e, n = list(r["entries"]), sum(r["manifest"]["learned_entries"].values())
        bad = list(e)
        bad[B.CORE_ENTRIES] = e[B.CORE_ENTRIES + 1]  # duplicate
        with self.assertRaises(B.BuildError):
            B.check_vocabulary(bad, P2A, n)
        bad = list(e)
        bad[300] = b"\xe0\xa4\x95\xe0\xa4\x95\xe0\xa4\x95"  # core changed
        with self.assertRaises(B.BuildError):
            B.check_vocabulary(bad, P2A, n)
        bad = list(e)
        bad[B.CORE_ENTRIES] = "कಕ".encode()  # mixed-script learned entry
        with self.assertRaises(B.BuildError):
            B.check_vocabulary(bad, P2A, n)
        with self.assertRaises(B.BuildError):
            B.check_vocabulary(e[:-1], P2A, n)


class Segmentation(unittest.TestCase):
    def test_aksharas(self):
        cases = {
            "नमस्ते": ["न", "म", "स्ते"],
            "क्षत्रिय": ["क्ष", "त्रि", "य"],
            "क़िला": ["क़ि", "ला"],
            "आइए": ["आ", "इ", "ए"],
            "हिंदी": ["हिं", "दी"],
            "क्\u200dष": ["क्\u200dष"],           # ZWJ inside a conjunct
            "क्": ["क्"],                          # final virama
            "कन्नड": ["क", "न्न", "ड"],
            "ಕನ್ನಡ": ["ಕ", "ನ್ನ", "ಡ"],
            "ಬೆಂಗಳೂರು": ["ಬೆಂ", "ಗ", "ಳೂ", "ರು"],
            "१२।": ["१", "२", "।"],                 # other code points on their own
            "\u093eक": ["\u093e", "क"],            # stray sign at run start
        }
        for text, expect in cases.items():
            self.assertEqual(SEG.aksharas(text), expect, text)

    def test_runs(self):
        runs = list(SEG.runs("ab कमल  ಕನ್ನಡ,हि\u200cन्दी xಕ"))
        self.assertEqual(runs, [("hi", True, "कमल"), ("kn", True, "ಕನ್ನಡ"), ("hi", False, "हि\u200cन्दी"), ("kn", False, "ಕ")])
        self.assertEqual(list(SEG.runs("कಕ")), [("hi", False, "क"), ("kn", False, "ಕ")])  # script change splits runs
        self.assertEqual(list(SEG.runs("\u200dक")), [("hi", False, "क")])  # a leading ZWJ is not part of a run
        self.assertEqual(list(SEG.runs("")), [])
        self.assertEqual(list(SEG.runs("plain ascii 123 \t\0")), [])


class Candidates(unittest.TestCase):
    def counts(self, *texts):
        return B.count_candidates([{"doc_id": "t", "text": t} for t in texts], SEG)

    def test_exact_counts(self):
        c = self.counts("कमल कमल")["hi"]
        enc = lambda s: s.encode()  # noqa: E731
        self.assertEqual(c, Counter({enc("क"): 2, enc("म"): 2, enc("ल"): 2, enc("कम"): 2, enc("मल"): 2, enc("कमल"): 2,
                                     enc(" क"): 1, enc(" कम"): 1, enc(" कमल"): 1}))

    def test_lines_and_documents_do_not_join(self):
        c = self.counts("कम\nल", "क")["hi"]
        self.assertEqual(c, Counter({"क".encode(): 2, "म".encode(): 1, "ल".encode(): 1, "कम".encode(): 1}))

    def test_sixteen_byte_limit(self):
        c = self.counts(" कखगघङच")["hi"]  # 6 aksharas of 3 bytes = 18 bytes
        self.assertTrue(all(len(k) <= 16 for k in c))
        self.assertIn(" कखगघङ".encode(), c)  # 1 + 15 = 16 bytes
        self.assertNotIn("कखगघङच".encode(), c)
        self.assertEqual(max(len(SEG.aksharas(k.decode().strip())) for k in c), 5)

    def test_languages_separate(self):
        c = self.counts("कम ಕಮ")
        self.assertEqual(set(c["hi"]), {"क".encode(), "म".encode(), "कम".encode()})
        self.assertEqual(set(c["kn"]), {"ಕ".encode(), "ಮ".encode(), "ಕಮ".encode(), " ಕ".encode(), " ಕಮ".encode()})

    def test_overlapping_occurrences_all_count(self):
        # D3: every occurrence counts, including overlapping ones inside one run.
        c = self.counts("ककक")["hi"]
        self.assertEqual(c["कक".encode()], 2)
        self.assertEqual(c["ककक".encode()], 1)
        self.assertEqual(c["क".encode()], 3)

    def test_no_separate_akshara_cap(self):
        # The only length bound is 16 bytes; with 3-byte code points that is <= 5 code points, so <= 5 aksharas.
        self.assertFalse(hasattr(B, "MAX_AKSHARAS"))
        c = self.counts("कखगघङ")["hi"]
        self.assertIn("कखगघङ".encode(), c)  # 5 aksharas, 15 bytes
        c = self.counts("क्षत्र")["hi"]  # 2 conjunct aksharas = 6 code points = 18 bytes: the pair is too long, each alone is kept
        self.assertEqual(set(c), {"क्ष".encode(), "त्र".encode()})


class StreamingEquivalence(unittest.TestCase):
    """build() counts distinct runs and ranks shard by shard; it must equal the in-memory reference exactly."""

    def test_runs_regex_equals_reference(self):
        rng = random.Random(3)
        alphabet = ["क", "ष", "्", "ि", "़", "ಕ", "ನ", "್", "ು", " ", "a", "\u200d", "\u200c", "।", "1", "😀"]
        for _ in range(500):
            line = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 20)))
            self.assertEqual(list(SEG.runs(line)), list(SEG.runs_reference(line)), repr(line))

    def test_sharded_counts_equal_reference(self):
        train = B.split(B.read_corpus(FIXTURE)[0])[0]
        ref = B.count_candidates(train, SEG)
        run_counts = Counter()
        B.count_runs(train, SEG, run_counts)
        runs = [(lang, sp, tuple(a.encode() for a in SEG.aksharas(r)), tuple(a[0] for a in SEG.aksharas(r)), m)
                for (lang, sp, r), m in run_counts.items()]
        for shards in (1, 3, 7):
            merged = {lang: Counter() for lang in B.SCRIPTS}
            for sh in range(shards):
                part = B.count_candidates_from_runs(runs, sh, shards)
                for lang in B.SCRIPTS:
                    self.assertFalse(set(merged[lang]) & set(part[lang]))  # shards are disjoint
                    merged[lang].update(part[lang])
            self.assertEqual(merged, ref)

    def test_ranked_top_equals_full_ranking(self):
        train = B.split(B.read_corpus(FIXTURE)[0])[0]
        ref = B.count_candidates(train, SEG)
        g, st = B.Greedy(P2A), set(P2A)
        full = {lang: B.rank(ref[lang], g, st) for lang in B.SCRIPTS}
        run_counts = Counter()
        B.count_runs(train, SEG, run_counts)
        runs = [(lang, sp, tuple(a.encode() for a in SEG.aksharas(r)), tuple(a[0] for a in SEG.aksharas(r)), m)
                for (lang, sp, r), m in run_counts.items()]
        for shards, keep in ((1, 10 ** 6), (5, 100), (8, 1000)):
            top, positive = B.ranked_top(runs, g, st, keep, shards)
            for lang in B.SCRIPTS:
                self.assertEqual(top[lang], full[lang][:keep])
                self.assertEqual(positive[lang], len(full[lang]))

    def test_build_identical_for_any_shard_count_and_split_files(self):
        base = fixture_build()["blob"]
        for shards in (2, 9):
            self.assertEqual(B.build(FIXTURE, LABEL, allow_unfilled=True, shards=shards)["blob"], base)
        docs = B.read_corpus(FIXTURE)[0]
        with tempfile.TemporaryDirectory() as d:  # the same documents split over two files, read in order
            a, b = corpus(d, docs[:100], "a.jsonl"), corpus(d, docs[100:], "b.jsonl")
            r = B.build([a, b], LABEL, allow_unfilled=True, shards=3)
            self.assertEqual(r["blob"], base)
            self.assertEqual([f["documents"] for f in r["manifest"]["corpus"]["files"]], [100, len(docs) - 100])
            with self.assertRaises(B.BuildError):  # duplicate doc_id across files
                B.build([a, a], LABEL, allow_unfilled=True)

    def test_freeze_requires_check_dir_outside_repo(self):
        script = str(ROOT / "codec/p2c/build_vocabulary.py")
        with tempfile.TemporaryDirectory() as d:
            base = [sys.executable, "-I", script, "--corpus", str(FIXTURE), "--corpus-label", "label without the guard words",
                    "--out-dir", d, "--freeze"]
            for extra in ([], ["--check-dir", str(ROOT / "results")]):
                p = subprocess.run(base + extra, capture_output=True, text=True)
                self.assertNotEqual(p.returncode, 0)
                self.assertIn("check", p.stderr)
            self.assertEqual(list(pathlib.Path(d).iterdir()), [])


class Ranking(unittest.TestCase):
    def setUp(self):
        self.g, self.s = B.Greedy(P2A), set(P2A)

    def test_score_and_tie_breaks(self):
        enc = lambda s: s.encode()  # noqa: E731
        counter = Counter({enc("कल"): 3, enc("कम"): 3, enc("कमल"): 1, enc("का"): 100, enc("गख"): 4})
        ranked = self.B_rank(counter)
        # गख: 4*(2-1)=4; कम, कल: 3 each, same length -> bytes ascending; कमल: 1*(3-1)=2; का is a P2a entry -> skipped.
        self.assertEqual([r[0] for r in ranked], [enc("गख"), enc("कम"), enc("कल"), enc("कमल")])
        counter = Counter({enc("कम"): 2, enc("कमल"): 1})  # equal score 2 -> longer first
        self.assertEqual([r[0] for r in self.B_rank(counter)], [enc("कमल"), enc("कम")])

    def test_single_akshara_conjuncts_rank_when_they_save_tokens(self):
        enc = lambda s: s.encode()  # noqa: E731
        ranked = self.B_rank(Counter({enc("क्ष"): 5, enc("का"): 50, enc("क"): 90}))
        # क्ष = P2a "क्" + "ष" (2 tokens): score 5. का and क are P2a entries: skipped.
        self.assertEqual([(r[0], r[2], r[3]) for r in ranked], [(enc("क्ष"), 2, 5)])

    def test_ranking_independent_of_insertion_order(self):
        items = list(fixture_build()["ranked"]["kn"])
        counter = Counter({e: c for e, c, _, _ in items})
        shuffled = list(counter.items())
        random.Random(7).shuffle(shuffled)
        self.assertEqual(self.B_rank(Counter(dict(shuffled))), self.B_rank(counter))

    def B_rank(self, counter):
        return B.rank(counter, self.g, self.s)


class Greedy(unittest.TestCase):
    def test_matches_naive_longest_prefix(self):
        e = fixture_build()["entries"]
        g, vocab = B.Greedy(e), set(e)
        rng = random.Random(11)
        learned = e[B.CORE_ENTRIES:B.CORE_ENTRIES + 50]
        for _ in range(300):
            parts = [rng.choice(learned + [b" ", b"a", b"\x00", "क".encode(), "्".encode(), bytes([rng.randrange(256)])]) for _ in range(8)]
            data = b"".join(parts)
            data = data[:rng.randrange(len(data) + 1)]  # arbitrary cut, possibly inside a code point
            pos, naive = 0, []
            while pos < len(data):
                ln = next(n for n in range(min(16, len(data) - pos), 0, -1) if n == 1 or data[pos:pos + n] in vocab)
                naive.append(data[pos:pos + ln])
                pos += ln
            self.assertEqual(g.tokenize(data), naive)
            self.assertEqual(b"".join(naive), data)

    def test_learned_entry_wins_over_p2a_pieces(self):
        r = fixture_build()
        t = r["entries"][B.CORE_ENTRIES]
        self.assertEqual(B.Greedy(r["entries"]).tokenize(t), [t])
        self.assertGreater(len(B.Greedy(P2A).tokenize(t)), 1)


class SizeModelAndL(unittest.TestCase):
    def test_p2b_width_rule(self):
        self.assertEqual(B.p2b_blob([]), (0, 0, 0))
        self.assertEqual(B.p2b_blob([b"a"]), (1 + 2 + 13, 2, 1))  # narrow 1+1+2+1=5 is not < 3
        toks = [bytes([i % 256, i // 256]) for i in range(256)] * 4
        self.assertEqual(B.p2b_blob(toks)[1:], (1, 256))
        toks = [bytes([i % 256, i // 256]) for i in range(257)] * 4
        self.assertEqual(B.p2b_blob(toks)[1:], (2, 257))
        n, m = 1024, 256
        self.assertEqual(B.p2b_blob([bytes([i % m]) * 2 for i in range(n)])[0], 1 + 2 + 2 * m + n + 13)

    # These tests check the selection PROCEDURE only. The fixture is meaningless text; its L is not a real setting.
    def cols(self):
        return B.heldout_columns(B.split(B.read_corpus(FIXTURE)[0])[1])

    def test_heldout_columns_per_language(self):
        cols = self.cols()
        self.assertEqual(set(cols), {"hi", "kn"})
        self.assertTrue(cols["hi"] and cols["kn"])
        for lang, other in (("hi", "kn"), ("kn", "hi")):
            for col in cols[lang]:
                self.assertTrue(len(col) <= 64)
                text = b"".join(col).decode()
                lo, hi = B.SCRIPTS[lang]
                olo, ohi = B.SCRIPTS[other]
                self.assertGreater(sum(lo <= ord(ch) <= hi for ch in text), sum(olo <= ord(ch) <= ohi for ch in text))

    def test_doc_language(self):
        self.assertEqual(B.doc_language("कम ಕ"), "hi")
        self.assertEqual(B.doc_language("क ಕಮ"), "kn")
        self.assertIsNone(B.doc_language("क ಕ"))
        self.assertIsNone(B.doc_language("ascii only"))

    def test_eligibility_and_objective(self):
        r, cols = fixture_build(), self.cols()
        hi, kn = len(r["ranked"]["hi"]), len(r["ranked"]["kn"])
        top = 2 * min(hi, kn)  # largest L both languages can fill
        cands = (0, 256, top, top + 2, 4096)
        chosen, table = B.select_l(P2A, r["ranked"], cols, cands)
        rows = {row["L"]: row for row in table}
        self.assertEqual([L for L in sorted(cands) if rows[L]["eligible"]], [0, 256, top])
        base = rows[0]["heldout_bytes_p2b"]
        self.assertEqual(rows[0]["heldout_bytes"], base)
        self.assertEqual(rows[0]["objective"], "1/1")  # L = 0 is P2a, i.e. P2b
        for L in (0, 256, top):
            obj = sum(Fraction(rows[L]["heldout_bytes"][g], base[g]) for g in ("hi", "kn")) / 2
            self.assertEqual(rows[L]["objective"], f"{obj.numerator}/{obj.denominator}")
        best = min((Fraction(rows[L]["objective"]), L) for L in (0, 256, top))
        self.assertEqual(chosen, best[1])
        with self.assertRaises(B.BuildError):  # none of the default L can be filled from the fixture
            B.select_l(P2A, r["ranked"], cols, B.DEFAULT_L_CANDIDATES)

    def test_ties_go_to_smaller_l(self):
        r, cols = fixture_build(), self.cols()
        # With --allow-unfilled every default L gives the same vocabulary (the fixture fills < 2,048 per language): all tie.
        chosen, table = B.select_l(P2A, r["ranked"], cols, B.DEFAULT_L_CANDIDATES, allow_unfilled=True)
        self.assertEqual(len({row["objective"] for row in table}), 1)
        self.assertEqual(chosen, 4096)
        self.assertFalse(any(row["fillable"] for row in table))  # recorded honestly even when allowed

    def test_objective_weights_languages_equally(self):
        r, cols = fixture_build(), self.cols()
        doubled = {"hi": cols["hi"] * 3, "kn": cols["kn"]}  # tripling one language's held-out bytes must not change the choice
        cands = (0, 256, 1024)
        a = B.select_l(P2A, r["ranked"], cols, cands)
        b = B.select_l(P2A, r["ranked"], doubled, cands)
        self.assertEqual(a[0], b[0])
        self.assertEqual([row["objective"] for row in a[1]], [row["objective"] for row in b[1]])

    def test_selection_requires_both_languages(self):
        r, cols = fixture_build(), self.cols()
        with self.assertRaises(B.BuildError):
            B.select_l(P2A, r["ranked"], {"hi": cols["hi"], "kn": []}, (0, 256))

    def test_fixed_l_must_be_fillable(self):
        with self.assertRaises(B.BuildError):
            B.build(FIXTURE, LABEL, fixed_l=4096)
        self.assertEqual(B.build(FIXTURE, LABEL, fixed_l=4096, allow_unfilled=True)["entries"], fixture_build()["entries"])

    def test_heldout_split_is_by_doc_id_hash(self):
        docs = B.read_corpus(FIXTURE)[0]
        train, held = B.split(docs)
        self.assertEqual(len(train) + len(held), len(docs))
        self.assertTrue(all(int(hashlib.sha256(d["doc_id"].encode()).hexdigest(), 16) % 20 == 0 for d in held))
        self.assertFalse({d["doc_id"] for d in train} & {d["doc_id"] for d in held})
        # Held-out text never contributes to counts: building from train only gives the same ranking.
        with tempfile.TemporaryDirectory() as d:
            only_train = corpus(d, train)
            self.assertEqual(B.build(only_train, LABEL, fixed_l=4096, allow_unfilled=True)["entries"], fixture_build()["entries"])


class Guards(unittest.TestCase):
    def test_refuses_evaluation_datasets(self):
        for p in ("datasets/phase1/kn_hi_v1.jsonl", "datasets/phase1_en_mixed/en_mixed_v1.jsonl"):
            with self.assertRaises(B.BuildError):
                B.read_corpus(ROOT / p)

    def test_refuses_path_under_datasets(self):
        with self.assertRaises(B.BuildError):
            B.read_corpus(ROOT / "datasets" / "phase1" / "README.md")

    def test_malformed_corpora(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(B.BuildError):
                B.read_corpus(corpus(d, [{"doc_id": "a", "text": "x"}, {"doc_id": "a", "text": "y"}]))
            with self.assertRaises(B.BuildError):
                B.read_corpus(corpus(d, [{"doc_id": 1, "text": "x"}]))
            p = pathlib.Path(d) / "s.jsonl"
            p.write_text('{"doc_id": "a", "text": "\\ud800"}\n', encoding="ascii")
            with self.assertRaises(B.BuildError):
                B.read_corpus(p)

    def test_cli_refuses_codec_dir_and_freezing_fixture(self):
        script = str(ROOT / "codec/p2c/build_vocabulary.py")
        base = [sys.executable, "-I", script, "--corpus", str(FIXTURE), "--corpus-label", LABEL]
        p = subprocess.run(base + ["--out-dir", str(ROOT / "codec/p2c/should_not_exist")], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        p = subprocess.run(base + ["--out-dir", str(ROOT / "codec/p2c/should_not_exist"), "--freeze"], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        with tempfile.TemporaryDirectory() as d:  # a frozen L must come from held-out selection with full quotas
            other = [sys.executable, "-I", script, "--corpus", str(FIXTURE), "--corpus-label", "label without the guard words",
                     "--out-dir", d, "--freeze"]
            for extra in (["--fixed-l", "256"], ["--allow-unfilled"], ["--l-candidates", "256,1024"], ["--l-candidates", "4096,8192,16384"]):
                p = subprocess.run(other + extra, capture_output=True, text=True)
                self.assertNotEqual(p.returncode, 0)
                self.assertIn("refusing to freeze", p.stderr)
            self.assertEqual(list(pathlib.Path(d).iterdir()), [])
        self.assertFalse((ROOT / "codec/p2c/should_not_exist").exists())


if __name__ == "__main__":
    unittest.main(verbosity=1)
