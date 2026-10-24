"""Tests for experiments/indic_tokenizer/hf_bpe.py on the real Qwen3 tokenizer.json (from the upstream checkout).

Run: python3 -I tests/indic_tokenizer/test_hf_bpe.py
"""
import json
import pathlib
import random
import sys
import tempfile
import unicodedata
import unittest

sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments/indic_tokenizer"))
import hf_bpe  # noqa: E402

QWEN3 = ROOT / "external/token-vldb2026/tokenizers/qwen3.json"
QWEN3_SHA256 = "aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4"  # = Qwen/Qwen3-0.6B tokenizer.json (LFS oid), rev c1899de2
TK = hf_bpe.ByteLevelBPE(QWEN3)
SAMPLES = ["", " ", "  \n\t \r\n", "Hello, world!", "नमस्ते दुनिया", "भारत की राजधानी नई दिल्ली है।", "ಕನ್ನಡ ಭಾಷೆ", "ಬೆಂಗಳೂರು",
           "मिश्रित ಮಿಶ್ರ mixed text 123", "0123456789 ०१२ ೦೧೨", "😀👍🏽 👨‍👩‍👧 ₹100", "क्‍ष ಕ್‌ಷ", "a\x00b\x01c",
           "<|im_start|>user<|im_end|>", "<|endoftext|>", "'s 'T 're", "line1\nline2\r\n\tend  ", "ñ é ü Ω Ж 中文 日本語 العربية"]


def reference_bpe(tk, piece):
    """Deliberately simple reference: merge the single lowest-ranked adjacent pair (leftmost on ties), one at a time."""
    word = [tk.byte_enc[b] for b in piece.encode("utf-8")]
    while True:
        best = None
        for i in range(len(word) - 1):
            r = tk.ranks.get((word[i], word[i + 1]))
            if r is not None and (best is None or r < best[0]):
                best = (r, i)
        if best is None:
            return [tk.vocab[t] for t in word]
        i = best[1]
        word[i:i + 2] = [word[i] + word[i + 1]]


def reference_bpe_bytes(tk, data):
    word = [tk.byte_enc[b] for b in data]
    while True:
        best = None
        for i in range(len(word) - 1):
            r = tk.ranks.get((word[i], word[i + 1]))
            if r is not None and (best is None or r < best[0]):
                best = (r, i)
        if best is None:
            return [tk.vocab[t] for t in word]
        i = best[1]
        word[i:i + 2] = [word[i] + word[i + 1]]


class Basics(unittest.TestCase):
    def test_identity_and_known_answers(self):
        self.assertEqual(TK.sha256, QWEN3_SHA256)
        self.assertEqual(TK.base_size, 151669)
        self.assertTrue(TK.nfc)
        self.assertEqual(TK.encode("Hello, world!"), [9707, 11, 1879, 0])  # Qwen's published encoding of this string

    def test_round_trip_and_valid_ids(self):
        for s in SAMPLES:
            ids = TK.encode(s)
            self.assertEqual(TK.decode(ids), unicodedata.normalize("NFC", s), repr(s))
            self.assertTrue(all(0 <= i < TK.base_size and i not in TK.special for i in ids), repr(s))
        self.assertEqual(TK.encode(""), [])

    def test_special_text_is_not_a_control_token(self):
        for s in ("<|im_start|>", "<|endoftext|>", "x<|im_end|>y"):
            self.assertFalse(set(TK.encode(s)) & set(TK.special), s)

    def test_normalization_is_the_models(self):
        # The base tokenizer normalizes to NFC, so non-NFC input is not reproduced byte for byte (a property of the model's
        # tokenizer, reported by the evaluator as exact vs exact-after-NFC).
        self.assertEqual(TK.decode(TK.encode("é")), "é")
        self.assertEqual(TK.decode(TK.encode("क़")), "क़")  # composition-excluded: NFC decomposes it

    def test_bpe_matches_simple_reference(self):
        rng = random.Random(5)
        alphabet = list("कखगषमनरलतदि्ीुेोंः ಕನಡಬರಳಾಿು್ೆಂ aeiouxyz0129,.!😀") + ["‍"]
        pieces = []
        for s in SAMPLES:
            pieces += TK.pre_tokenize(TK.normalize(s))
        for _ in range(400):
            t = "".join(rng.choice(alphabet) for _ in range(rng.randrange(1, 14)))
            pieces += TK.pre_tokenize(TK.normalize(t))
        for p in pieces:
            self.assertEqual(TK._bpe(p), reference_bpe(TK, p), repr(p))

    def test_every_vocabulary_entry_rebuilds_as_its_own_id(self):
        # Self-consistency of the merge table and merge loop: each of the 151,643 entries, from its own bytes, is one token.
        misses = []
        for tok, i in TK.vocab.items():
            b = bytes(TK.byte_dec[c] for c in tok)
            try:
                text = b.decode("utf-8")
            except UnicodeDecodeError:
                text = None
            if text is not None:
                TK._cache.pop(text, None)
                if TK._bpe(text) != [i]:
                    misses.append(i)
            elif reference_bpe_bytes(TK, b) != [i]:
                misses.append(i)
        self.assertEqual(misses, [])

    def test_regex_classes(self):
        self.assertEqual(TK.pre_tokenize("नमस्ते"), ["नमस", "्त", "े"])  # combining marks are not \p{L}: words split
        self.assertEqual(TK.pre_tokenize(" ಕನ್ನಡ"), [" ಕನ", "್ನಡ"])
        self.assertEqual(TK.pre_tokenize("१२3"), ["१", "२", "3"])  # \p{N} matches Devanagari digits singly (Qwen: \p{N})
        self.assertEqual("".join(TK.pre_tokenize("a b  c\n\nd")), "a b  c\n\nd")


class Extension(unittest.TestCase):
    def setUp(self):
        self.tk = hf_bpe.ByteLevelBPE(QWEN3)

    def test_added_tokens_ids_and_leftmost_longest(self):
        ids = self.tk.add_tokens(["नमस्ते", " नमस्ते", "नम", "ಕನ್ನಡ"])
        self.assertEqual(ids, [151669, 151670, 151671, 151672])
        self.assertEqual(self.tk.size(), 151673)
        self.assertEqual(self.tk.encode("नमस्ते"), [151669])          # spans pre-token boundaries
        self.assertEqual(self.tk.encode(" नमस्ते"), [151670])         # longest at the leftmost position
        self.assertEqual(self.tk.encode("नमक"), [151671] + TK.encode("क"))
        self.assertEqual(self.tk.decode(self.tk.encode("x नमस्ते, ಕನ್ನಡ!")), "x नमस्ते, ಕನ್ನಡ!")

    def test_base_behaviour_outside_extension(self):
        self.tk.add_tokens(["नमस्ते", "ಕನ್ನಡ"])
        for s in ("Hello, world!", "plain ASCII 123", "中文 Ж", "😀", "", "दुनिया"):
            self.assertEqual(self.tk.encode(s), TK.encode(s), s)

    def test_invalid_extensions(self):
        with self.assertRaises(ValueError):
            self.tk.add_tokens([""])
        with self.assertRaises(ValueError):
            self.tk.add_tokens(["क़"])  # not NFC-stable: could never match normalized text
        self.tk.add_tokens(["नम"])
        with self.assertRaises(ValueError):
            self.tk.add_tokens(["नम"])
        with self.assertRaises(KeyError):
            self.tk.token_bytes(999999)


class FailClosed(unittest.TestCase):
    def test_unsupported_configurations(self):
        d = json.loads(QWEN3.read_text())
        variants = []
        for path, value in ((("normalizer",), {"type": "NFKC"}), (("model", "type"), "Unigram"), (("model", "byte_fallback"), True),
                            (("decoder",), {"type": "Metaspace"}), (("pre_tokenizer",), {"type": "Whitespace"})):
            v = json.loads(json.dumps(d))
            tgt = v
            for k in path[:-1]:
                tgt = tgt[k]
            tgt[path[-1]] = value
            variants.append(v)
        v = json.loads(json.dumps(d))
        v["pre_tokenizer"]["pretokenizers"][0]["pattern"]["Regex"] = r"\p{Lu}+"
        variants.append(v)
        with tempfile.TemporaryDirectory() as td:
            for k, v in enumerate(variants):
                p = pathlib.Path(td) / f"v{k}.json"
                p.write_text(json.dumps(v))
                with self.assertRaises(hf_bpe.UnsupportedTokenizer, msg=str(k)):
                    hf_bpe.ByteLevelBPE(p)


if __name__ == "__main__":
    unittest.main(verbosity=1)
