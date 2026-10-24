# Licence notice for the P2c vocabulary file

**Applies to:** `codec/p2c/p2c_vocabulary_v1.bin` (SHA-256 `1e12dc488beddfdf0242268fd17cdd90e93d834be0a81e6780754bcbc629dc84`) and its manifest, `p2c_vocabulary_v1.manifest.json`.
**Does not apply to:** the code in this repository, which is not covered by this notice. The repository has no licence file yet.

## Licence
The vocabulary file is distributed under the **Creative Commons Attribution-ShareAlike 4.0 International licence (CC BY-SA 4.0)**: https://creativecommons.org/licenses/by-sa/4.0/legalcode.en

## Attribution
- **Source:** the vocabulary's learned entries (IDs 5,248–38,015: Hindi 5,248–21,631, Kannada 21,632–38,015) are derived from text of:
  - **Hindi Wikipedia** (`hiwiki`), dump **20261001**, file `hiwiki-20261001-pages-articles.xml.bz2` (SHA-1 `eb8929c38f0791f87a93c6d65919226b3068a0da`), https://dumps.wikimedia.org/hiwiki/20261001/
  - **Kannada Wikipedia** (`knwiki`), dump **20261001**, file `knwiki-20261001-pages-articles.xml.bz2` (SHA-1 `66f6d094b04f750821ce00d5f4270023e1df0755`), https://dumps.wikimedia.org/knwiki/20261001/
- **Authors:** Wikipedia contributors. Each article's authors are listed in its page history on hi.wikipedia.org and kn.wikipedia.org.
- **Source licence:** the original text is available under CC BY-SA 4.0 and the GFDL (https://dumps.wikimedia.org/legal.html; Wikimedia Terms of Use §7, https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use). This vocabulary uses the CC BY-SA 4.0 option.

## Changes made
- **Conversion:** article text (namespace 0, no redirects) was extracted with `codec/p2c/convert_wikipedia.py` (`p2c-wikipedia-converter-v1`, markup rule `wikitext-strip-v1`, no Unicode normalization).
- **Segmentation and ranking:** the text was split into aksharas, substrings of at most 16 bytes were counted, and the most frequent token-saving substrings were selected and ranked by `codec/p2c/build_vocabulary.py` (`p2c-builder-v3`, rules D1–D8 in `docs/phase2_p2c_report.md` §3).
- **No text reproduced:** the file contains no running text, only individual entries of at most 16 bytes.
- **Non-learned entries:** IDs 0–5,247 and the ASCII entries are taken unchanged from the project's P2a vocabulary, which is not derived from Wikipedia.

## What this notice does not settle
- **Whether a licence is legally required:** it is **unresolved** whether a frequency-ranked list of short substrings is *Adapted Material* under CC BY-SA 4.0, or an extraction from a database under its §4 (sui generis database rights).
- **Why CC BY-SA anyway:** the project releases the file under CC BY-SA 4.0 as a conservative choice. This notice is not a legal opinion and does not resolve that question.
- **Downstream share-alike:** anyone redistributing an adapted version of this file must do so under CC BY-SA 4.0, or a compatible licence, with attribution.
- **Possible infringing content:** Wikimedia states that dumps may contain unnoticed infringing content.
