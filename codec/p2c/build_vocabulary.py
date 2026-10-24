"""P2c vocabulary builder: frozen P2a core + learned multi-akshara/word entries + truncated P2a ASCII (docs/phase2_p2c_plan.md §4).

STATUS: prototype. No approved training corpus exists (D3), so NO frozen P2c vocabulary is produced by this repository.
The builder is exercised only with the synthetic unit-test fixture in tests/p2c/fixtures/. A vocabulary built from that fixture
says nothing about real-world compression.

Inputs (and only these):
  1. codec/p2a/p2a_vocabulary_v1.bin, checked against its frozen SHA-256 (the P2b vocabulary is the P2a vocabulary).
  2. A training corpus: JSONL, one document per line, {"doc_id": str, "text": str}; lines of a document are split on "\n".
     The builder refuses the controlled evaluation datasets (by SHA-256 and by path under datasets/).
Output layout (65,536 entries, so global IDs stay u16 and the P2b codec, HCC1 codec 3, is reused unchanged):
  IDs 0-5,247         P2a core, unchanged (single bytes, akshara, space+akshara)
  next L/2            learned Devanagari entries, in rank order (fewer only with --allow-unfilled)
  next L/2            learned Kannada entries, in rank order (fewer only with --allow-unfilled)
  remaining           P2a's ASCII entries in P2a (o200k rank) order, truncated so the total is exactly 65,536
Design decisions (resolved before any real data; docs/phase2_p2c_report.md §3):
  - candidates: 1 or more aksharas from one single-script run, bounded only by the 16-byte codec limit (which already caps an
    Indic candidate at 5 code points), with and (at run start, after a space) without the leading space;
  - an L is eligible only if BOTH languages fill their L/2 quota; quotas never move between languages, so a selected or frozen
    vocabulary has no unfilled learned slot. --allow-unfilled (tests and diagnostics only; refused with --freeze) instead
    gives unfilled slots back to ASCII entries;
  - L is chosen on the held-out TRAINING split: per language, held-out bytes relative to P2b (the P2a vocabulary); the mean of
    the two ratios is minimised (exact fractions); ties go to the smaller L.
File format: as P1/P2a ("P1V1", u32 LE count, then u8 length + bytes per entry).

Usage:
  python3 -I codec/p2c/build_vocabulary.py --corpus C1.jsonl [--corpus C2.jsonl ...] --corpus-label LABEL --out-dir DIR [--shards N]
      [--check-dir DIR]   (required with --freeze; the held-out check file contains training text and must stay outside the repo)
  test/diagnostic only: [--fixed-l L] [--allow-unfilled] [non-default --l-candidates]   (all refused with --freeze)
"""
import argparse
import hashlib
import heapq
import importlib.util
import json
import pathlib
import re
import sys
import unicodedata
from collections import Counter
from fractions import Fraction

sys.dont_write_bytecode = True  # importing the P1/P2c builders must not leave __pycache__ in the repository

ROOT = pathlib.Path(__file__).resolve().parents[2]
P2A = ROOT / "codec" / "p2a" / "p2a_vocabulary_v1.bin"
P2A_SHA256 = "c99ff52fa92fa7c8be541c0358c10acd678aeaa98764bb474ef06077faa7face"
P1_BUILDER = ROOT / "codec" / "p1" / "build_vocabulary.py"
BUILDER_VERSION = "p2c-builder-v3"  # v3: streaming, exact sharded counting, several corpus files (same rules and output as v2)
MAX_ENTRIES = 65536
MAX_TOKEN_BYTES = 16
CORE_ENTRIES = 5248  # P2a IDs 0-5,247
MIN_AKSHARAS = 1  # no separate upper bound: MAX_TOKEN_BYTES is the binding limit (3-byte Indic code points -> <= 5)
DEFAULT_L_CANDIDATES = (4096, 8192, 16384, 32768)
HELDOUT_MODULUS = 20  # SHA-256(doc_id) mod 20 == 0 -> heldout (5%)
HELDOUT_COLUMN_LINES = 64
FOOTER_BYTES = 13  # BTT2 footer
HCC1_HEADER_BYTES = 6
ZW = ("‌", "‍")
SCRIPTS = {"hi": (0x0900, 0x097F), "kn": (0x0C80, 0x0CFF)}  # language group <- script block (Devanagari, Kannada)
# Controlled evaluation datasets: never a training corpus.
FORBIDDEN_CORPUS_SHA256 = {
    "359269f4dbacd71e9442e3a1b38785e603698931fe4e8afa22e51b5ae36bb6fc": "datasets/phase1/kn_hi_v1.jsonl",
    "6c4685c24ac3603d19ba9121a3c564f88cd3f78542cbc8efec090f7c031d47b0": "datasets/phase1_en_mixed/en_mixed_v1.jsonl",
}


class BuildError(Exception):
    pass


# ---------------------------------------------------------------------------- vocabulary I/O
def read_vocabulary(blob):
    if blob[:4] != b"P1V1":
        raise BuildError("vocabulary: bad magic")
    count, pos, entries = int.from_bytes(blob[4:8], "little"), 8, []
    for _ in range(count):
        n = blob[pos]
        entries.append(bytes(blob[pos + 1:pos + 1 + n]))
        pos += 1 + n
    if pos != len(blob):
        raise BuildError("vocabulary: trailing bytes")
    return entries


def serialize(entries):
    return b"P1V1" + len(entries).to_bytes(4, "little") + b"".join(bytes([len(t)]) + t for t in entries)


def load_p2a(path=P2A):
    blob = pathlib.Path(path).read_bytes()
    if hashlib.sha256(blob).hexdigest() != P2A_SHA256:
        raise BuildError("P2a vocabulary does not match its frozen SHA-256; P2c must be derived from the frozen P2a/P2b vocabulary")
    entries = read_vocabulary(blob)
    if len(entries) != MAX_ENTRIES or any(not all(b < 128 for b in e) for e in entries[CORE_ENTRIES:]) \
            or any(all(b < 128 for b in e) for e in entries[256:CORE_ENTRIES]):
        raise BuildError("unexpected P2a layout")
    return entries


# ---------------------------------------------------------------------------- greedy tokenizer (same rule as codec/include/p1_codec.hpp)
class Greedy:
    def __init__(self, entries):
        self.by_len = [set() for _ in range(MAX_TOKEN_BYTES + 1)]
        for e in entries:
            self.by_len[len(e)].add(e)

    def tokenize(self, data):
        """Greedy longest prefix, 16 bytes down to 2, else one single-byte fallback token. Returns token byte strings."""
        out, pos, n = [], 0, len(data)
        while pos < n:
            for length in range(min(MAX_TOKEN_BYTES, n - pos), 1, -1):
                piece = data[pos:pos + length]
                if piece in self.by_len[length]:
                    out.append(piece)
                    pos += length
                    break
            else:
                out.append(data[pos:pos + 1])
                pos += 1
        return out


# ---------------------------------------------------------------------------- akshara segmentation (P1/P2a structural rules)
def _load_p1_classify():
    spec = importlib.util.spec_from_file_location("hashcode_p1_builder", P1_BUILDER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if unicodedata.unidata_version != mod.EXPECTED_UNICODE:
        raise BuildError(f"Unicode {unicodedata.unidata_version} != {mod.EXPECTED_UNICODE}")
    return mod


class Segmenter:
    def __init__(self):
        p1 = _load_p1_classify()
        self.cons, self.nukta, self.signs, self.virama, self.vowels = set(), set(), set(), set(), set()
        for lo, hi in SCRIPTS.values():
            chars = p1.block_chars(lo, hi)
            c, n, s = p1.classify(chars)
            self.cons |= set(c)
            self.nukta |= set(n)
            self.signs |= set(s)
            self.virama |= {ch for ch in chars if unicodedata.name(ch, "").endswith("SIGN VIRAMA")}
            self.vowels |= {ch for ch in chars if unicodedata.category(ch) == "Lo" and " LETTER " in unicodedata.name(ch, "") and ch not in c}

    @staticmethod
    def script_of(ch):
        o = ord(ch)
        for lang, (lo, hi) in SCRIPTS.items():
            if lo <= o <= hi:
                return lang
        return None

    _RUN = re.compile("|".join(f"(?P<{lang}>[\\u{lo:04X}-\\u{hi:04X}][\\u{lo:04X}-\\u{hi:04X}\\u200C\\u200D]*)"
                               for lang, (lo, hi) in SCRIPTS.items()))

    def runs(self, line):
        """Maximal single-script runs in a line (ZWJ/ZWNJ inside a run belong to it). Yields (lang, leading_space, run)."""
        for m in self._RUN.finditer(line):
            yield m.lastgroup, m.start() > 0 and line[m.start() - 1] == " ", m.group()

    def runs_reference(self, line):
        """Reference implementation of runs() (character loop), kept for the equivalence test."""
        i, n = 0, len(line)
        while i < n:
            lang = self.script_of(line[i])
            if lang is None:
                i += 1
                continue
            j = i + 1
            while j < n and (self.script_of(line[j]) == lang or line[j] in ZW):
                j += 1
            yield lang, i > 0 and line[i - 1] == " ", line[i:j]
            i = j

    def aksharas(self, run):
        """consonant(+nukta)(virama[ZW]* consonant(+nukta))*(sign|ZW)* | independent vowel (sign|ZW)* | any other code point (ZW)*"""
        out, i, n = [], 0, len(run)
        while i < n:
            ch, j = run[i], i + 1
            if ch in self.cons:
                if j < n and run[j] in self.nukta:
                    j += 1
                while j < n and run[j] in self.virama:
                    k = j + 1
                    while k < n and run[k] in ZW:
                        k += 1
                    if k < n and run[k] in self.cons:
                        j = k + 1
                        if j < n and run[j] in self.nukta:
                            j += 1
                    else:
                        break
                while j < n and (run[j] in self.signs or run[j] in ZW):
                    j += 1
            elif ch in self.vowels:
                while j < n and (run[j] in self.signs or run[j] in ZW):
                    j += 1
            else:
                while j < n and run[j] in ZW:
                    j += 1
            out.append(run[i:j])
            i = j
        return out


# ---------------------------------------------------------------------------- corpus
def corpus_info(path):
    """SHA-256 and size of a corpus file (streamed), after refusing the controlled evaluation datasets."""
    path = pathlib.Path(path).resolve()
    try:
        path.relative_to(ROOT / "datasets")
        raise BuildError("refusing a corpus under datasets/ (controlled evaluation data)")
    except ValueError:
        pass
    h, n = hashlib.sha256(), 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            n += len(chunk)
    digest = h.hexdigest()
    if digest in FORBIDDEN_CORPUS_SHA256:
        raise BuildError(f"refusing evaluation dataset {FORBIDDEN_CORPUS_SHA256[digest]} as a training corpus")
    return digest, n


def iter_corpus(path, seen=None):
    """Validated documents of one JSONL corpus file, streamed in file order. `seen` collects doc_ids across files."""
    seen = set() if seen is None else seen
    with open(path, "r", encoding="utf-8", newline="\n") as f:
        for k, raw in enumerate(f):
            if not raw.strip():
                continue
            d = json.loads(raw)
            if not isinstance(d.get("doc_id"), str) or not isinstance(d.get("text"), str):
                raise BuildError(f"corpus line {k + 1}: needs string doc_id and text")
            try:
                d["text"].encode("utf-8")
            except UnicodeEncodeError:
                raise BuildError(f"corpus line {k + 1}: text is not encodable as UTF-8 (lone surrogate)") from None
            if d["doc_id"] in seen:
                raise BuildError(f"duplicate doc_id {d['doc_id']}")
            seen.add(d["doc_id"])
            yield {"doc_id": d["doc_id"], "text": d["text"]}


def read_corpus(path):
    """Whole corpus in memory (small files and tests only)."""
    digest, n = corpus_info(path)
    return list(iter_corpus(path)), digest, n


def is_heldout(doc_id):
    return int.from_bytes(hashlib.sha256(doc_id.encode("utf-8")).digest(), "big") % HELDOUT_MODULUS == 0


def split(docs):
    train = [d for d in docs if not is_heldout(d["doc_id"])]
    heldout = [d for d in docs if is_heldout(d["doc_id"])]
    return train, heldout


# ---------------------------------------------------------------------------- candidates and ranking
def count_candidates(docs, seg):
    """Counter per language of candidate byte strings: >= 1 consecutive aksharas in a run, <= 16 bytes, with and (at run start,
    after a space) without the leading space. Every occurrence counts, including overlapping ones.
    Reference implementation (all counts in memory); build() uses the equivalent count_runs + ranked_top."""
    counts = {lang: Counter() for lang in SCRIPTS}
    for d in docs:
        for line in d["text"].split("\n"):
            for lang, space, run in seg.runs(line):
                ak = [a.encode("utf-8") for a in seg.aksharas(run)]
                c = counts[lang]
                for i in range(len(ak)):
                    acc = b""
                    for j in range(i, len(ak)):
                        acc += ak[j]
                        if len(acc) > MAX_TOKEN_BYTES:
                            break
                        if j - i + 1 >= MIN_AKSHARAS:
                            c[acc] += 1
                            if i == 0 and space and len(acc) + 1 <= MAX_TOKEN_BYTES:
                                c[b" " + acc] += 1
    return counts


def count_runs(docs, seg, run_counts):
    """Multiplicity of each distinct (language, leading space, run) in the training documents."""
    for d in docs:
        for line in d["text"].split("\n"):
            for key in seg.runs(line):
                run_counts[key] += 1


def shard_of(first_char, shards):
    """Shard of a candidate: by its first code point after an optional leading space (determined by the candidate itself)."""
    return ord(first_char) % shards


def count_candidates_from_runs(runs, shard, shards):
    """Candidate counts for one shard, from distinct runs with multiplicities; identical to count_candidates() restricted
    to candidates whose shard_of(first code point) == shard. `runs` = [(lang, space, aksharas as bytes, first chars, count)]."""
    counts = {lang: Counter() for lang in SCRIPTS}
    for lang, space, ak, first, mult in runs:
        c = counts[lang]
        for i in range(len(ak)):
            if shard_of(first[i], shards) != shard:
                continue
            acc = b""
            for j in range(i, len(ak)):
                acc += ak[j]
                if len(acc) > MAX_TOKEN_BYTES:
                    break
                c[acc] += mult
                if i == 0 and space and len(acc) + 1 <= MAX_TOKEN_BYTES:
                    c[b" " + acc] += mult
    return counts


def rank_key(row):
    return (-row[3], -len(row[0]), row[0])


def ranked_top(runs, p2a_greedy, p2a_set, keep, shards):
    """Exact top-`keep` ranked candidates per language (same order as rank() on the full counts), computed shard by shard so
    that only one shard's counts are in memory. Also returns the number of candidates with a positive score."""
    tops = {lang: [] for lang in SCRIPTS}
    positive = {lang: 0 for lang in SCRIPTS}
    for shard in range(shards):
        counts = count_candidates_from_runs(runs, shard, shards)
        for lang in SCRIPTS:
            r = rank(counts[lang], p2a_greedy, p2a_set)
            positive[lang] += len(r)
            tops[lang].extend(r[:keep])
        del counts
    return {lang: sorted(tops[lang], key=rank_key)[:keep] for lang in SCRIPTS}, positive


def rank(counter, p2a_greedy, p2a_set):
    """Deterministic ranking: score = count x (P2a tokens - 1); ties: longer first, then bytes ascending. Entries already in P2a
    and candidates that save nothing are skipped. Returns [(entry, count, p2a_tokens, score)] in rank order."""
    scored = []
    for cand, cnt in counter.items():
        if cand in p2a_set:
            continue
        t = len(p2a_greedy.tokenize(cand))
        score = cnt * (t - 1)
        if score > 0:
            scored.append((cand, cnt, t, score))
    scored.sort(key=rank_key)
    return scored


def assemble(p2a, ranked, learned):
    """Vocabulary for a given L (learned entries, split 50/50 between hi and kn)."""
    if learned < 0 or learned % 2 or CORE_ENTRIES + learned > MAX_ENTRIES:
        raise BuildError(f"L={learned} must be even and at most {MAX_ENTRIES - CORE_ENTRIES}")
    quota = learned // 2
    picked = {lang: [r[0] for r in ranked[lang][:quota]] for lang in SCRIPTS}
    core, ascii_ = p2a[:CORE_ENTRIES], p2a[CORE_ENTRIES:]
    n_learned = sum(len(v) for v in picked.values())
    entries = core + picked["hi"] + picked["kn"] + ascii_[:MAX_ENTRIES - CORE_ENTRIES - n_learned]
    check_vocabulary(entries, p2a, n_learned)
    return entries, {lang: len(v) for lang, v in picked.items()}


def check_vocabulary(entries, p2a, n_learned):
    if len(entries) != MAX_ENTRIES or len(set(entries)) != MAX_ENTRIES:
        raise BuildError("P2c vocabulary must have exactly 65,536 distinct entries")
    if entries[:CORE_ENTRIES] != p2a[:CORE_ENTRIES]:
        raise BuildError("P2c IDs 0-5,247 must equal P2a")
    if any(len(e) > MAX_TOKEN_BYTES or len(e) < 1 for e in entries):
        raise BuildError("entry length outside 1..16 bytes")
    for e in entries[CORE_ENTRIES:CORE_ENTRIES + n_learned]:
        text = e.decode("utf-8")  # raises on invalid UTF-8
        body = text[1:] if text.startswith(" ") else text
        langs = {Segmenter.script_of(ch) for ch in body if ch not in ZW}
        if len(langs) != 1 or None in langs or body[0] in ZW:
            raise BuildError(f"learned entry {e!r} is not a single-script run (plus optional leading space)")


# ---------------------------------------------------------------------------- held-out size model (P2b codec, HCC1 codec 3)
def varint_bytes(v):
    n = 1
    while v >= 0x80:
        v >>= 7
        n += 1
    return n


def p2b_blob(tokens):
    """(blob bytes, width, distinct) of the P2b blob for a token sequence (codec/include/p2b_codec.hpp rule)."""
    n = len(tokens)
    if n == 0:
        return 0, 0, 0
    m = len(set(tokens))
    narrow = 1 + varint_bytes(m) + 2 * m + n
    wide = 1 + 2 * n
    if m <= 256 and narrow < wide:
        return narrow + FOOTER_BYTES, 1, m
    return wide + FOOTER_BYTES, 2, m


def doc_language(text):
    """Language group of a document: the script with more code points; None if neither script occurs or they are equal."""
    n = {lang: sum(lo <= ord(ch) <= hi for ch in text) for lang, (lo, hi) in SCRIPTS.items()}
    if n["hi"] == n["kn"]:
        return None
    return max(n, key=n.get)


def heldout_columns(heldout):
    """Per language group: that group's held-out lines, in document order, in columns of 64 lines."""
    out = {}
    for lang in SCRIPTS:
        lines = [line.encode("utf-8") for d in heldout if doc_language(d["text"]) == lang for line in d["text"].split("\n")]
        out[lang] = [lines[i:i + HELDOUT_COLUMN_LINES] for i in range(0, len(lines), HELDOUT_COLUMN_LINES)]
    return out


def column_cost(greedy, values):
    payload = b"".join(values)
    tokens = greedy.tokenize(payload)
    blob, width, distinct = p2b_blob(tokens) if payload else (0, 0, 0)
    total = HCC1_HEADER_BYTES + varint_bytes(len(values)) + sum(varint_bytes(len(v)) for v in values) + varint_bytes(blob) + blob
    return {"total": total, "blob": blob, "tokens": len(tokens), "distinct": distinct, "width": width, "payload": payload}


def eligible(ranked, learned):
    return all(len(ranked[lang]) >= learned // 2 for lang in SCRIPTS)


def heldout_totals(entries, columns):
    g = Greedy(entries)
    return {lang: sum(column_cost(g, col)["total"] for col in cols) for lang, cols in columns.items()}


def select_l(p2a, ranked, columns, candidates, allow_unfilled=False):
    """Choose L on the held-out training split.
    Objective: mean over hi and kn of (held-out HCC1+P2b bytes with this L) / (the same with the P2a vocabulary, i.e. P2b),
    in exact fractions, so each language counts equally whatever its share of the corpus. Ties go to the smaller L.
    An L is ineligible unless both languages fill L/2 slots (unless allow_unfilled). Returns (L, per-L table)."""
    if any(not columns[lang] for lang in SCRIPTS):
        raise BuildError("held-out split must contain columns for both languages to select L")
    base = heldout_totals(p2a, columns)
    table, best = [], None
    for learned in sorted(set(candidates)):
        filled = {lang: min(len(ranked[lang]), learned // 2) for lang in SCRIPTS}
        fillable = eligible(ranked, learned)
        row = {"L": learned, "fillable": fillable, "eligible": allow_unfilled or fillable, "learned_filled": filled}
        if row["eligible"]:
            entries, _ = assemble(p2a, ranked, learned)
            totals = heldout_totals(entries, columns)
            objective = sum(Fraction(totals[lang], base[lang]) for lang in SCRIPTS) / len(SCRIPTS)
            row.update({"heldout_bytes": totals, "heldout_bytes_p2b": base, "objective": f"{objective.numerator}/{objective.denominator}",
                        "objective_float": float(objective)})
            if best is None or objective < best[0]:  # strict: equal objectives keep the smaller L (sorted ascending)
                best = (objective, learned)
        table.append(row)
    if best is None:
        raise BuildError("no candidate L is eligible: the training corpus cannot fill L/2 learned entries for both languages")
    return best[1], table


# ---------------------------------------------------------------------------- build
def build(corpus, corpus_label, l_candidates=DEFAULT_L_CANDIDATES, fixed_l=None, allow_unfilled=False, shards=1, progress=None):
    """Build a P2c vocabulary. `corpus` is one JSONL path or a list of paths, read in the given order."""
    p2a = load_p2a()
    paths = [corpus] if isinstance(corpus, (str, pathlib.Path)) else list(corpus)
    if not paths:
        raise BuildError("no corpus file")
    if shards < 1:
        raise BuildError("shards must be >= 1")
    files = []
    for path in paths:
        digest, size = corpus_info(path)
        files.append({"file": pathlib.Path(path).name, "sha256": digest, "bytes": size})
    seg = Segmenter()
    run_counts, heldout, seen = Counter(), [], set()
    n_docs = n_train = 0
    for f, path in zip(files, paths):
        f["documents"] = 0
        for d in iter_corpus(path, seen):
            n_docs += 1
            f["documents"] += 1
            if is_heldout(d["doc_id"]):
                heldout.append(d)
            else:
                n_train += 1
                count_runs((d,), seg, run_counts)
            if progress and n_docs % 20000 == 0:
                progress(f"read {n_docs} documents")
    if not n_train:
        raise BuildError("training split is empty")
    runs = []
    for (lang, space, run), mult in run_counts.items():
        ak = seg.aksharas(run)
        runs.append((lang, space, tuple(a.encode("utf-8") for a in ak), tuple(a[0] for a in ak), mult))
    distinct_runs = len(runs)
    del run_counts
    runs.sort(key=lambda r: (r[0], r[1], r[2]))  # deterministic iteration order
    keep = max([fixed_l] if fixed_l is not None else list(l_candidates)) // 2
    p2a_greedy, p2a_set = Greedy(p2a), set(p2a)
    ranked, positive = ranked_top(runs, p2a_greedy, p2a_set, keep, shards)
    del runs
    if progress:
        progress(f"ranked: {positive}")
    columns = heldout_columns(heldout)
    if fixed_l is not None:
        if not allow_unfilled and not eligible(ranked, fixed_l):
            raise BuildError(f"L={fixed_l} cannot be filled for both languages (use a smaller L, or --allow-unfilled for tests)")
        chosen, table = fixed_l, None
    else:
        chosen, table = select_l(p2a, ranked, columns, l_candidates, allow_unfilled)
    entries, filled = assemble(p2a, ranked, chosen)
    blob = serialize(entries)
    digest = hashlib.sha256(blob).hexdigest()
    n_learned = sum(filled.values())
    manifest = {
        "vocabulary": "p2c-learned", "builder_version": BUILDER_VERSION, "entries": len(entries), "file_bytes": len(blob),
        "sha256": digest, "table_id_hex": digest[:16], "max_token_bytes": max(map(len, entries)),
        "L_selected": chosen, "L_selection": table, "L_candidates": sorted(l_candidates) if fixed_l is None else None,
        "learned_entries": filled, "learned_slots_returned_to_ascii": chosen - n_learned, "allow_unfilled": allow_unfilled,
        "id_ranges": {"p2a_core": [0, CORE_ENTRIES - 1],
                      "learned_hi": [CORE_ENTRIES, CORE_ENTRIES + filled["hi"] - 1] if filled["hi"] else None,
                      "learned_kn": [CORE_ENTRIES + filled["hi"], CORE_ENTRIES + n_learned - 1] if filled["kn"] else None,
                      "ascii": [CORE_ENTRIES + n_learned, MAX_ENTRIES - 1]},
        "candidates_ranked": {lang: len(ranked[lang]) for lang in SCRIPTS},
        "candidates_with_positive_score": positive, "distinct_training_runs": distinct_runs, "shards": shards,
        "corpus": {"label": corpus_label, "files": files, "sha256": files[0]["sha256"] if len(files) == 1 else None,
                   "bytes": sum(f["bytes"] for f in files), "documents": n_docs,
                   "train_documents": n_train, "heldout_documents": len(heldout),
                   "heldout_columns": {lang: len(c) for lang, c in columns.items()},
                   "heldout_documents_without_language": sum(doc_language(d["text"]) is None for d in heldout)},
        "rules": {"candidates": f">= {MIN_AKSHARAS} akshara(s) of one single-script run, <= {MAX_TOKEN_BYTES} bytes, with/without leading space",
                  "score": "count x (p2a_tokens - 1), every occurrence counted, no re-scoring", "ties": "longer first, then bytes ascending",
                  "split": "strict 50/50 hi/kn; an L is eligible only if both quotas fill",
                  "heldout": f"sha256(doc_id) mod {HELDOUT_MODULUS} == 0", "heldout_column_lines": HELDOUT_COLUMN_LINES,
                  "heldout_language": "per document, the script with more code points",
                  "L_objective": "mean over hi, kn of heldout bytes / heldout bytes with P2a vocabulary (P2b)", "L_tie_break": "smaller L"},
        "inputs": {"p2a_vocabulary": {"path": str(P2A.relative_to(ROOT)), "sha256": P2A_SHA256}},
        "evaluation_data_read": False,
    }
    check_rows = []
    g = Greedy(entries)
    for i, col in enumerate(col for lang in SCRIPTS for col in columns[lang]):
        c = column_cost(g, col)
        check_rows.append((i, c["payload"].hex(), c["tokens"], c["distinct"], c["width"], c["blob"]))
    return {"entries": entries, "blob": blob, "manifest": manifest, "ranked": ranked, "check_rows": check_rows}


def write_outputs(result, out_dir, name, check_dir=None):
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    check_dir = pathlib.Path(check_dir) if check_dir is not None else out_dir
    check_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.bin").write_bytes(result["blob"])
    (out_dir / f"{name}.sha256").write_text(f"{result['manifest']['sha256']}  {name}.bin\n")
    (out_dir / f"{name}.manifest.json").write_text(json.dumps(result["manifest"], indent=2) + "\n")
    with open(check_dir / f"{name}.heldout_check.tsv", "w", encoding="ascii") as f:
        f.write("column_index\tpayload_hex\ttokens\tdistinct\twidth\tblob_bytes\n")
        for row in result["check_rows"]:
            f.write("\t".join(map(str, row)) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", required=True, type=pathlib.Path, action="append", help="JSONL corpus file; repeat to read several in order")
    ap.add_argument("--shards", type=int, default=1, help="count candidates in N passes to bound memory (result is identical)")
    ap.add_argument("--check-dir", type=pathlib.Path, default=None, help="where to write the held-out check file (contains training text)")
    ap.add_argument("--corpus-label", required=True, help="recorded in the manifest, e.g. 'synthetic unit-test fixture (not a real corpus)'")
    ap.add_argument("--out-dir", required=True, type=pathlib.Path)
    ap.add_argument("--name", default="p2c_vocabulary")
    ap.add_argument("--l-candidates", default=",".join(map(str, DEFAULT_L_CANDIDATES)))
    ap.add_argument("--fixed-l", type=int, default=None, help="tests/diagnostics only: skip L selection")
    ap.add_argument("--allow-unfilled", action="store_true", help="tests/diagnostics only: unfilled learned slots go back to ASCII")
    ap.add_argument("--freeze", action="store_true", help="allow writing under codec/ (only for an approved, non-synthetic corpus)")
    args = ap.parse_args(argv)
    out = args.out_dir.resolve()
    try:
        out.relative_to(ROOT / "codec")
        inside_codec = True
    except ValueError:
        inside_codec = False
    if inside_codec and not args.freeze:
        sys.exit("refusing to write under codec/ without --freeze (no P2c vocabulary is frozen until a training corpus is approved)")
    if args.freeze and ("synthetic" in args.corpus_label.lower() or "fixture" in args.corpus_label.lower()):
        sys.exit("refusing to freeze a vocabulary learned from a synthetic fixture")
    if args.freeze and (args.fixed_l is not None or args.allow_unfilled):
        sys.exit("refusing to freeze with --fixed-l or --allow-unfilled: a frozen L must come from held-out selection with full quotas")
    try:
        candidates = tuple(int(x) for x in args.l_candidates.split(","))
    except ValueError:
        sys.exit("--l-candidates must be a comma-separated list of integers")
    if args.freeze and tuple(sorted(set(candidates))) != DEFAULT_L_CANDIDATES:
        sys.exit(f"refusing to freeze with non-default --l-candidates: a frozen L must come from the predeclared {DEFAULT_L_CANDIDATES} (D8)")
    if args.freeze:
        if args.check_dir is None:
            sys.exit("--freeze needs --check-dir outside the repository: the held-out check file contains training text")
        try:
            args.check_dir.resolve().relative_to(ROOT)
            sys.exit("refusing --check-dir inside the repository: the held-out check file contains training text")
        except ValueError:
            pass
    try:
        result = build(args.corpus, args.corpus_label, candidates, args.fixed_l, args.allow_unfilled, args.shards,
                       progress=lambda msg: print(msg, file=sys.stderr, flush=True))
    except BuildError as e:
        sys.exit(f"P2c build error: {e}")
    write_outputs(result, out, args.name, args.check_dir)
    m = result["manifest"]
    print(json.dumps({k: m[k] for k in ("sha256", "L_selected", "learned_entries", "learned_slots_returned_to_ascii", "L_selection")}, indent=1))


if __name__ == "__main__":
    main()
