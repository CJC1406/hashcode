"""Dependency-free reader for Hugging Face byte-level BPE tokenizers (tokenizer.json), with added-token extension.

Why: no tokenizer library (tokenizers/tiktoken/transformers) is installed and installing needs approval. This module reads the
model's OWN tokenizer.json and produces its native token IDs. It supports exactly the configuration used by Qwen2/Qwen3 and
Llama 3 style tokenizers and refuses anything else (fail closed):
  normalizer      : null or {"type": "NFC"}
  pre_tokenizer   : Sequence[Split(Regex, behavior=Isolated, invert=false), ByteLevel(add_prefix_space=false, use_regex=false)]
  model           : BPE (byte-level alphabet; no byte_fallback, no dropout, no continuing_subword_prefix/end_of_word_suffix)
  decoder         : ByteLevel
Fidelity: the pipeline follows the tokenizers library's documented behaviour (normalize -> split on added tokens ->
pre-tokenize -> byte-level map -> BPE merges by rank). It has NOT been checked against the reference library on this machine
(not installed); see docs/indic_tokenizer.md. Regex classes \\p{L} and \\p{N} are generated from Python's unicodedata
(Unicode 16.0.0), which may differ from the library's tables for recently added characters.

Special (control) tokens are never produced from text: text such as "<|im_start|>" is tokenized as ordinary characters.
Extension tokens are added like tokenizers' `add_tokens` (non-special, normalized): matched leftmost-longest on the
normalized text BEFORE pre-tokenization, so they can span pre-token boundaries.
"""
import hashlib
import json
import pathlib
import re
import sys
import unicodedata

sys.dont_write_bytecode = True


class UnsupportedTokenizer(Exception):
    pass


def bytes_to_unicode():
    """GPT-2 byte-level alphabet: a reversible map from the 256 byte values to printable code points."""
    bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1)) + list(range(ord("®"), ord("ÿ") + 1))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return {b: chr(c) for b, c in zip(bs, cs)}


def _class_ranges(prefix):
    """Regex character-class body for all code points whose general category starts with `prefix` ('L' or 'N')."""
    ranges, start, prev = [], None, None
    for cp in range(0x110000):
        if 0xD800 <= cp <= 0xDFFF:
            ok = False
        else:
            ok = unicodedata.category(chr(cp)).startswith(prefix)
        if ok:
            if start is None:
                start = cp
            prev = cp
        elif start is not None:
            ranges.append((start, prev))
            start = None
    if start is not None:
        ranges.append((start, prev))
    esc = lambda c: "\\U%08x" % c  # noqa: E731
    return "".join(esc(a) if a == b else f"{esc(a)}-{esc(b)}" for a, b in ranges)


_CLASSES = {}


def translate_regex(pattern):
    """Translate the tokenizer's Oniguruma-style pattern to Python `re`: \\p{L}, \\p{N} (inside or outside a class)."""
    for k in ("L", "N"):
        if k not in _CLASSES:
            _CLASSES[k] = _class_ranges(k)
    out, i, in_class = [], 0, False
    while i < len(pattern):
        c = pattern[i]
        if c == "\\" and pattern.startswith(("\\p{L}", "\\p{N}"), i):
            body = _CLASSES[pattern[i + 3]]
            out.append(body if in_class else f"[{body}]")
            i += 5
            continue
        if c == "\\" and i + 1 < len(pattern):
            if pattern[i + 1] == "p":
                raise UnsupportedTokenizer(f"unsupported Unicode property in regex: {pattern[i:i + 8]}")
            out.append(pattern[i:i + 2])
            i += 2
            continue
        if c == "[" and not in_class:
            in_class = True
        elif c == "]" and in_class:
            in_class = False
        out.append(c)
        i += 1
    return re.compile("".join(out))


class ByteLevelBPE:
    def __init__(self, path):
        self.path = pathlib.Path(path)
        raw = self.path.read_bytes()
        self.sha256 = hashlib.sha256(raw).hexdigest()
        d = json.loads(raw)
        norm = d.get("normalizer")
        if norm not in (None, {"type": "NFC"}):
            raise UnsupportedTokenizer(f"unsupported normalizer {norm}")
        self.nfc = norm == {"type": "NFC"}
        pre = d.get("pre_tokenizer") or {}
        steps = pre.get("pretokenizers") if pre.get("type") == "Sequence" else None
        if not steps or len(steps) != 2:
            raise UnsupportedTokenizer("pre_tokenizer must be Sequence[Split, ByteLevel]")
        split, bl = steps
        if split.get("type") != "Split" or split.get("behavior") != "Isolated" or split.get("invert") or "Regex" not in (split.get("pattern") or {}):
            raise UnsupportedTokenizer(f"unsupported Split pre-tokenizer {split}")
        if bl.get("type") != "ByteLevel" or bl.get("add_prefix_space") or bl.get("use_regex"):
            raise UnsupportedTokenizer(f"unsupported ByteLevel pre-tokenizer {bl}")
        if (d.get("decoder") or {}).get("type") != "ByteLevel":
            raise UnsupportedTokenizer("decoder must be ByteLevel")
        m = d.get("model") or {}
        if m.get("type") != "BPE" or m.get("byte_fallback") or m.get("dropout") or m.get("continuing_subword_prefix") or m.get("end_of_word_suffix"):
            raise UnsupportedTokenizer("model must be plain byte-level BPE")
        self.pattern_source = split["pattern"]["Regex"]
        self.regex = translate_regex(self.pattern_source)
        self.ignore_merges = bool(m.get("ignore_merges"))
        self.vocab = m["vocab"]
        merges = m["merges"]
        self.ranks = {}
        for i, mg in enumerate(merges):
            a, b = mg if isinstance(mg, list) else mg.split(" ", 1)
            self.ranks.setdefault((a, b), i)
        self.byte_enc = bytes_to_unicode()
        self.byte_dec = {v: k for k, v in self.byte_enc.items()}
        self.id_to_token = {i: t for t, i in self.vocab.items()}
        self.special = {}
        for t in d.get("added_tokens", []):
            self.id_to_token.setdefault(t["id"], None)
            self.special[t["id"]] = t["content"]
        if any(len(ch) != 1 or ch not in self.byte_dec for ch in self.byte_enc.values()) or not all(c in self.vocab for c in self.byte_enc.values()):
            raise UnsupportedTokenizer("vocabulary does not contain the full byte-level alphabet")
        self.base_size = max(self.id_to_token) + 1
        self.added = {}       # extension token text -> id
        self.added_ids = {}   # id -> text
        self._first = {}      # first char -> descending lengths
        self._cache = {}

    # ------------------------------------------------------------------ extension
    def add_tokens(self, texts):
        """Add non-special extension tokens (like tokenizers' add_tokens). IDs are assigned in order after all existing IDs.
        Each text must be non-empty, NFC-stable if the tokenizer normalizes, and new. Returns the assigned IDs."""
        ids = []
        for t in texts:
            if not t or (self.nfc and unicodedata.normalize("NFC", t) != t):
                raise ValueError(f"extension token {t!r} is empty or not NFC-stable")
            if t in self.added:
                raise ValueError(f"duplicate extension token {t!r}")
            new_id = self.size()
            self.added[t] = new_id
            self.added_ids[new_id] = t
            self._first.setdefault(t[0], set()).add(len(t))
            ids.append(new_id)
        self._lengths = {c: sorted(ls, reverse=True) for c, ls in self._first.items()}
        return ids

    def size(self):
        return self.base_size + len(self.added)

    # ------------------------------------------------------------------ encoding
    def normalize(self, text):
        return unicodedata.normalize("NFC", text) if self.nfc else text

    def pre_tokenize(self, text):
        """Pieces after the Split(Isolated) step (matches and any unmatched gaps, in order)."""
        pieces, pos = [], 0
        for mt in self.regex.finditer(text):
            if mt.start() > pos:
                pieces.append(text[pos:mt.start()])
            if mt.end() > mt.start():
                pieces.append(mt.group())
            pos = mt.end()
        if pos < len(text):
            pieces.append(text[pos:])
        return pieces

    def _bpe(self, piece):
        cached = self._cache.get(piece)
        if cached is not None:
            return cached
        word = [self.byte_enc[b] for b in piece.encode("utf-8")]
        joined = "".join(word)
        if self.ignore_merges and joined in self.vocab:
            out = [self.vocab[joined]]
        else:
            while len(word) > 1:
                best, best_rank = None, None
                for i in range(len(word) - 1):
                    r = self.ranks.get((word[i], word[i + 1]))
                    if r is not None and (best_rank is None or r < best_rank):
                        best, best_rank = (word[i], word[i + 1]), r
                if best is None:
                    break
                merged, i = [], 0
                while i < len(word):
                    if i < len(word) - 1 and (word[i], word[i + 1]) == best:
                        merged.append(word[i] + word[i + 1])
                        i += 2
                    else:
                        merged.append(word[i])
                        i += 1
                word = merged
            out = [self.vocab[t] for t in word]
        if len(self._cache) < 500000:
            self._cache[piece] = out
        return out

    def _split_added(self, text):
        """Leftmost-longest split on extension tokens: yields (is_added, segment)."""
        if not self.added:
            yield False, text
            return
        i, start, n = 0, 0, len(text)
        while i < n:
            match = None
            for ln in self._lengths.get(text[i], ()):
                if text[i:i + ln] in self.added:
                    match = ln
                    break
            if match:
                if i > start:
                    yield False, text[start:i]
                yield True, text[i:i + match]
                i += match
                start = i
            else:
                i += 1
        if start < n:
            yield False, text[start:]

    def encode(self, text, with_pieces=False):
        """Native token IDs for `text` (no special tokens are ever produced from text)."""
        ids, pieces = [], []
        for is_added, seg in self._split_added(self.normalize(text)):
            if is_added:
                ids.append(self.added[seg])
                pieces.append(seg)
                continue
            for p in self.pre_tokenize(seg):
                out = self._bpe(p)
                ids.extend(out)
                pieces.extend([p] if len(out) == 1 else [self.token_bytes(t).decode("utf-8", "replace") for t in out])
        return (ids, pieces) if with_pieces else ids

    # ------------------------------------------------------------------ decoding
    def token_bytes(self, tid):
        if tid in self.added_ids:
            return self.added_ids[tid].encode("utf-8")
        tok = self.id_to_token.get(tid)
        if tok is None:
            if tid in self.special:
                return self.special[tid].encode("utf-8")
            raise KeyError(f"token id {tid} not in vocabulary")
        return bytes(self.byte_dec[c] for c in tok)

    def decode_bytes(self, ids):
        return b"".join(self.token_bytes(t) for t in ids)

    def decode(self, ids):
        return self.decode_bytes(ids).decode("utf-8")
