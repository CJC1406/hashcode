"""SYNTHETIC UNIT-TEST FIXTURE GENERATOR. NOT A REAL CORPUS. NOT LANGUAGE DATA.

Generates a deterministic JSONL "training corpus" of meaningless pseudo-words. They are built only from fixed Unicode code-point
tables (Devanagari and Kannada consonants, vowel signs, virama, nukta, anusvara) and a fixed pseudo-random generator.
No text is read from any dataset, evaluation file or external source.

Purpose: exercise the P2c vocabulary builder (codec/p2c/build_vocabulary.py) in tests: segmentation, counting, ranking, L
selection, determinism and the vocabulary layout. A vocabulary learned from this fixture says NOTHING about compression of real
Hindi or Kannada and must never be used to claim compression effectiveness.

Each line: {"doc_id": "...", "text": "..."}; lines within a document are separated by "\n".
Run: python3 -I tests/p2c/fixtures/make_synthetic_corpus.py <out.jsonl>
"""
import hashlib
import json
import pathlib
import sys

FIXTURE_VERSION = "p2c-synthetic-fixture-v1"
# Pinned so that any change to the generator is noticed.
PINNED_SHA256 = "17457b4734b34f5fad917fe44a5ddc57529b62f1a5e3f139032b73b72d58a3a6"


class Rng:
    """xorshift64*: fixed, version-independent pseudo-random numbers (Python's random module is not used)."""

    def __init__(self, seed):
        self.s = seed & 0xFFFFFFFFFFFFFFFF or 1

    def next(self):
        s = self.s
        s ^= (s >> 12)
        s ^= (s << 25) & 0xFFFFFFFFFFFFFFFF
        s ^= (s >> 27)
        self.s = s
        return (s * 0x2545F4914F6CDD1D) & 0xFFFFFFFFFFFFFFFF

    def below(self, n):
        return self.next() % n

    def skewed(self, n):
        """Index in [0, n), heavily skewed toward 0 (a crude Zipf-like frequency)."""
        u = (self.next() >> 11) / float(1 << 53)
        return min(n - 1, int(n * u * u * u))


SCRIPTS = {
    "deva": {
        "consonants": [chr(c) for c in range(0x0915, 0x093A)],
        "signs": ["ा", "ि", "ी", "ु", "ू", "े", "ै", "ो", "ौ"],
        "vowels": ["अ", "आ", "इ", "उ", "ए"],
        "virama": "्", "nukta": "़", "anusvara": "ं", "punct": "।",
    },
    "knda": {
        "consonants": [chr(c) for c in range(0x0C95, 0x0CBA) if c not in (0x0CA9, 0x0CB4)],
        "signs": ["ಾ", "ಿ", "ೀ", "ು", "ೂ", "ೆ", "ೇ", "ೈ", "ೊ", "ೋ", "ೌ"],
        "vowels": ["ಅ", "ಆ", "ಇ", "ಉ", "ಎ"],
        "virama": "್", "nukta": None, "anusvara": "ಂ", "punct": None,
    },
}
ASCII_WORDS = ["zq", "xv", "id", "ok", "2031", "v7", "qq-1", "lorem", "data", "x"]


def akshara(rng, t, first):
    if first and rng.below(8) == 0:
        a = t["vowels"][rng.below(len(t["vowels"]))]
    else:
        a = t["consonants"][rng.below(len(t["consonants"]))]
        if t["nukta"] and rng.below(20) == 0:
            a += t["nukta"]
        if rng.below(6) == 0:  # conjunct
            a += t["virama"]
            if rng.below(10) == 0:
                a += "‍"  # ZWJ inside a conjunct
            a += t["consonants"][rng.below(len(t["consonants"]))]
        if rng.below(10) < 7:
            a += t["signs"][rng.below(len(t["signs"]))]
    if rng.below(12) == 0:
        a += t["anusvara"]
    return a


def lexicon(rng, t, n):
    words, seen = [], set()
    while len(words) < n:
        k = 2 + rng.below(5) if rng.below(10) else 7 + rng.below(4)  # mostly 2-6 aksharas, some 7-10 (longer than 16 bytes)
        w = "".join(akshara(rng, t, i == 0) for i in range(k))
        if w not in seen:
            seen.add(w)
            words.append(w)
    return words


def generate():
    rng = Rng(0x5EED_0F_C0FFEE)
    lex = {s: lexicon(rng, t, 300) for s, t in SCRIPTS.items()}
    docs = []
    plan = [("deva", 100), ("knda", 100), ("mixed", 40)]
    for kind, n in plan:
        for d in range(n):
            lines = []
            for _ in range(3):
                words = []
                for _ in range(6 + rng.below(5)):
                    script = kind if kind != "mixed" else ("deva" if rng.below(2) else "knda")
                    if kind == "mixed" and rng.below(3) == 0:
                        words.append(ASCII_WORDS[rng.skewed(len(ASCII_WORDS))])
                    else:
                        words.append(lex[script][rng.skewed(len(lex[script]))])
                line = " ".join(words)
                p = SCRIPTS["deva"]["punct"]
                if kind == "deva" and rng.below(3) == 0:
                    line += p
                lines.append(line)
            docs.append({"doc_id": f"synthetic-{kind}-{d:04d}", "text": "\n".join(lines)})
    return "".join(json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n" for doc in docs).encode("utf-8")


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: make_synthetic_corpus.py <out.jsonl>")
    data = generate()
    digest = hashlib.sha256(data).hexdigest()
    if digest != PINNED_SHA256:
        sys.exit(f"synthetic fixture SHA-256 {digest} != pinned {PINNED_SHA256}; the generator changed")
    pathlib.Path(sys.argv[1]).write_bytes(data)
    print(f"{FIXTURE_VERSION}: {len(data)} bytes, sha256 {digest}")


if __name__ == "__main__":
    main()
