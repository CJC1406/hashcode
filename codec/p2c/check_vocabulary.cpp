// P2c vocabulary checker. Reuses the existing format and codec definitions (codec/include/p1_codec.hpp, p2b_codec.hpp);
// it defines no format of its own.
// File format (P1V1, as written by codec/p2c/build_vocabulary.py): magic "P1V1" (the format version is part of the magic),
// u32 LE entry count, then per entry: u8 length (1..16) + bytes. Table ID = first 8 bytes of SHA-256 of the whole file.
//
// Usage: hashcode_p2c_check_vocabulary <vocab.bin> [--sha256-file F] [--p2a P2A.bin] [--heldout-check TSV] [--json OUT]
// Exit codes: 0 all checks pass; 1 a validation check failed; 2 usage error, unreadable or malformed vocabulary file.
// Prints a JSON summary on stdout (also to --json OUT); failures are listed under "failures".
#include "p2b_codec.hpp"
#include <cstdio>
#include <fstream>
#include <iostream>
#include <map>
#include <random>
#include <set>
#include <sstream>
#include <string>
#include <vector>
//---------------------------------------------------------------------------
using namespace hashcode;
//---------------------------------------------------------------------------
namespace {
//---------------------------------------------------------------------------
constexpr size_t requiredEntries = 65536;
constexpr size_t coreEntries = 5248;  // P2a IDs 0-5,247 (single bytes, akshara, space+akshara)
//---------------------------------------------------------------------------
std::span<const std::byte> bytes(const std::string& s) { return {reinterpret_cast<const std::byte*>(s.data()), s.size()}; }
std::string str(const std::vector<std::byte>& b) { return std::string(reinterpret_cast<const char*>(b.data()), b.size()); }
//---------------------------------------------------------------------------
std::string hex(const uint8_t* p, size_t n) {
   static const char* d = "0123456789abcdef";
   std::string s;
   for (size_t i = 0; i < n; ++i) {
      s += d[p[i] >> 4];
      s += d[p[i] & 15];
   }
   return s;
}
//---------------------------------------------------------------------------
std::string jsonEscape(const std::string& s) {
   std::string o;
   for (unsigned char c : s) {
      if (c == '"' || c == '\\') o += '\\', o += static_cast<char>(c);
      else if (c < 0x20) {
         char b[8];
         std::snprintf(b, sizeof b, "\\u%04x", c);
         o += b;
      } else o += static_cast<char>(c);
   }
   return o;
}
//---------------------------------------------------------------------------
bool isAscii(const std::string& e) {
   for (unsigned char c : e)
      if (c >= 128) return false;
   return true;
}
//---------------------------------------------------------------------------
/// Strict UTF-8 decode; false on any invalid sequence.
bool decodeUtf8(const std::string& s, std::vector<uint32_t>& cps) {
   for (size_t i = 0; i < s.size();) {
      const auto c = static_cast<unsigned char>(s[i]);
      size_t n = c < 0x80 ? 1 : (c >> 5) == 6 ? 2 : (c >> 4) == 14 ? 3 : (c >> 3) == 30 ? 4 : 0;
      if (!n || i + n > s.size()) return false;
      uint32_t cp = n == 1 ? c : n == 2 ? c & 0x1F : n == 3 ? c & 0x0F : c & 0x07;
      for (size_t k = 1; k < n; ++k) {
         const auto cc = static_cast<unsigned char>(s[i + k]);
         if ((cc >> 6) != 2) return false;
         cp = (cp << 6) | (cc & 0x3F);
      }
      if ((n == 2 && cp < 0x80) || (n == 3 && cp < 0x800) || (n == 4 && (cp < 0x10000 || cp > 0x10FFFF)) || (cp >= 0xD800 && cp <= 0xDFFF)) return false;
      cps.push_back(cp);
      i += n;
   }
   return true;
}
//---------------------------------------------------------------------------
/// 'h' Devanagari run, 'k' Kannada run (each with an optional leading space), 0 otherwise.
char learnedScript(const std::string& e) {
   std::vector<uint32_t> cps;
   if (!decodeUtf8(e, cps) || cps.empty()) return 0;
   size_t i = cps[0] == 0x20 ? 1 : 0;
   if (i >= cps.size() || cps[i] == 0x200C || cps[i] == 0x200D) return 0;
   char script = 0;
   for (; i < cps.size(); ++i) {
      const uint32_t c = cps[i];
      if (c == 0x200C || c == 0x200D) continue;
      const char s = (c >= 0x0900 && c <= 0x097F) ? 'h' : (c >= 0x0C80 && c <= 0x0CFF) ? 'k' : 0;
      if (!s || (script && s != script)) return 0;
      script = s;
   }
   return script;
}
//---------------------------------------------------------------------------
std::vector<uint8_t> readFile(const std::string& path) {
   std::ifstream in(path, std::ios::binary);
   if (!in) throw std::runtime_error("cannot open " + path);
   return std::vector<uint8_t>((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
}
//---------------------------------------------------------------------------
std::string unhex(const std::string& h) {
   if (h.size() % 2) throw std::runtime_error("odd hex length");
   std::string out;
   for (size_t i = 0; i < h.size(); i += 2) out.push_back(static_cast<char>(std::stoi(h.substr(i, 2), nullptr, 16)));
   return out;
}
//---------------------------------------------------------------------------
}
//---------------------------------------------------------------------------
int main(int argc, char** argv) {
   if (argc < 2) {
      std::cerr << "usage: hashcode_p2c_check_vocabulary <vocab.bin> [--sha256-file F] [--p2a P2A.bin] [--heldout-check TSV] [--json OUT]\n";
      return 2;
   }
   std::string path = argv[1], shaFile, p2aPath, heldout, jsonOut;
   for (int i = 2; i < argc; ++i) {
      std::string a = argv[i];
      if (i + 1 >= argc) {
         std::cerr << "missing value for " << a << "\n";
         return 2;
      }
      if (a == "--sha256-file") shaFile = argv[++i];
      else if (a == "--p2a") p2aPath = argv[++i];
      else if (a == "--heldout-check") heldout = argv[++i];
      else if (a == "--json") jsonOut = argv[++i];
      else {
         std::cerr << "unknown option " << a << "\n";
         return 2;
      }
   }
   std::vector<std::string> failures;
   auto fail = [&](const std::string& m) { failures.push_back(m); };

   std::vector<uint8_t> raw;
   std::unique_ptr<p1::Vocabulary> v;
   try {
      raw = readFile(path);
      v = std::make_unique<p1::Vocabulary>(path);  // magic, count range, entry lengths, truncation, trailing bytes, IDs 0-255, duplicates
   } catch (const std::exception& e) {
      std::cout << "{\"ok\": false, \"malformed\": true, \"error\": \"" << jsonEscape(e.what()) << "\"}\n";
      std::cerr << "malformed vocabulary: " << e.what() << "\n";
      return 2;
   }
   // Independent re-parse, as the Python builder's read_vocabulary() interprets the file.
   std::vector<std::string> parsed;
   std::map<size_t, size_t> lengths;
   {
      const uint32_t count = raw[4] | (raw[5] << 8) | (raw[6] << 16) | (uint32_t(raw[7]) << 24);
      size_t pos = 8;
      for (uint32_t i = 0; i < count; ++i) {
         const size_t n = raw[pos];
         parsed.emplace_back(reinterpret_cast<const char*>(raw.data() + pos + 1), n);
         ++lengths[n];
         pos += 1 + n;
      }
      size_t expectBytes = 8;
      for (const auto& e : parsed) expectBytes += 1 + e.size();
      if (expectBytes != raw.size()) fail("file size != 8 + sum(1 + entry length)");
   }
   if (v->size() != requiredEntries) fail("entry count " + std::to_string(v->size()) + " != 65536");
   for (size_t i = 0; i < parsed.size() && i < v->size(); ++i)
      if (parsed[i] != v->entry(static_cast<uint16_t>(i))) {
         fail("entry " + std::to_string(i) + " differs between the codec loader and the independent parse");
         break;
      }
   const auto digest = p1::detail::sha256(raw);
   const std::string sha = hex(digest.data(), 32), tableId = hex(v->tableId().data(), 8);
   if (tableId != sha.substr(0, 16)) fail("table ID is not the SHA-256 prefix");
   if (!shaFile.empty()) {
      std::ifstream in(shaFile);
      std::string want;
      in >> want;
      if (want != sha) fail("SHA-256 " + sha + " != " + shaFile + " (" + want + ")");
   }

   // Layout against P2a: core IDs equal, learned region (Devanagari then Kannada), then P2a's ASCII prefix.
   size_t learnedHi = 0, learnedKn = 0, learnedEnd = coreEntries, asciiEntries = 0;
   if (!p2aPath.empty() && v->size() == requiredEntries) {
      try {
         const p1::Vocabulary p2a(p2aPath);
         for (size_t i = 0; i < coreEntries; ++i)
            if (v->entry(static_cast<uint16_t>(i)) != p2a.entry(static_cast<uint16_t>(i))) {
               fail("core ID " + std::to_string(i) + " differs from P2a");
               break;
            }
         std::set<std::string> p2aSet;
         for (size_t i = 0; i < p2a.size(); ++i) p2aSet.insert(p2a.entry(static_cast<uint16_t>(i)));
         while (learnedEnd < v->size() && !isAscii(v->entry(static_cast<uint16_t>(learnedEnd)))) ++learnedEnd;
         bool seenKn = false;
         for (size_t i = coreEntries; i < learnedEnd; ++i) {
            const auto& e = v->entry(static_cast<uint16_t>(i));
            const char s = learnedScript(e);
            if (!s) {
               fail("learned ID " + std::to_string(i) + " is not a single-script Devanagari/Kannada entry (plus optional leading space)");
               break;
            }
            if (s == 'h' && seenKn) {
               fail("learned Devanagari ID " + std::to_string(i) + " after a Kannada entry");
               break;
            }
            seenKn |= s == 'k';
            (s == 'h' ? learnedHi : learnedKn)++;
            if (p2aSet.count(e)) {
               fail("learned ID " + std::to_string(i) + " is already a P2a entry");
               break;
            }
         }
         asciiEntries = v->size() - learnedEnd;
         for (size_t i = learnedEnd, j = coreEntries; i < v->size(); ++i, ++j)
            if (v->entry(static_cast<uint16_t>(i)) != p2a.entry(static_cast<uint16_t>(j))) {
               fail("ASCII ID " + std::to_string(i) + " is not P2a's ASCII entry " + std::to_string(j));
               break;
            }
      } catch (const std::exception& e) {
         fail(std::string("cannot load P2a vocabulary: ") + e.what());
      }
   }

   // Round trips through the actual P2b codec: every entry alone (must be exactly one token, its own ID), then mixed inputs.
   size_t roundTrips = 0;
   for (size_t i = 0; i < v->size(); ++i) {
      const auto& e = v->entry(static_cast<uint16_t>(i));
      size_t fb = 0;
      auto ids = v->tokenize(bytes(e), fb);
      p2b::Stats st;
      auto blob = p2b::encodeBlob(*v, bytes(e), st);
      if (ids.size() != 1 || ids[0] != i || str(p2b::decodeBlob(*v, blob)) != e || blob.size() != st.mappingBytes + st.tokenBytes + p2b::footerBytes) {
         fail("entry " + std::to_string(i) + " does not round-trip as its own single token");
         break;
      }
      ++roundTrips;
   }
   std::vector<std::string> inputs = {"", std::string(1, '\0'), "\xff\xfe\x80\xe0\xa4", "नमस्ते दुनिया", "ಕನ್ನಡ ಭಾಷೆ", "mixed मिश्रित ಮಿಶ್ರ 123\r\n\t",
                                      "\U0001F600‍\U0001F525 ₹", "क़ क़"};
   {
      std::string all;
      for (int b = 0; b < 256; ++b) all.push_back(static_cast<char>(b));
      inputs.push_back(all);
      std::string learned;
      for (size_t i = coreEntries; i < learnedEnd; ++i) learned += v->entry(static_cast<uint16_t>(i));
      inputs.push_back(learned);
      std::mt19937_64 rng(20261001);
      for (int k = 0; k < 200; ++k) {
         std::string s;
         for (int j = 0; j < 30; ++j) s += v->entry(static_cast<uint16_t>(rng() % v->size())) + (rng() % 4 ? "" : " ");
         inputs.push_back(s.substr(0, rng() % (s.size() + 1)));  // includes cuts inside code points
      }
   }
   size_t mixedRoundTrips = 0;
   for (const auto& s : inputs) {
      p2b::Stats st;
      auto blob = p2b::encodeBlob(*v, bytes(s), st);
      if (str(p2b::decodeBlob(*v, blob)) != s) {
         fail("mixed input does not round-trip");
         break;
      }
      ++mixedRoundTrips;
   }

   // Optional cross-check of the Python size model on held-out columns.
   size_t heldoutRows = 0;
   if (!heldout.empty()) {
      std::ifstream in(heldout);
      std::string line;
      if (!in || !std::getline(in, line)) fail("cannot read held-out check file");
      while (std::getline(in, line)) {
         std::istringstream f(line);
         std::string idx, hx;
         size_t tokens = 0, distinct = 0, width = 0, blobBytes = 0;
         std::getline(f, idx, '\t');
         std::getline(f, hx, '\t');
         f >> tokens >> distinct >> width >> blobBytes;
         try {
            const auto payload = unhex(hx);
            p2b::Stats st;
            auto blob = p2b::encodeBlob(*v, bytes(payload), st);
            const size_t got = payload.empty() ? 0 : blob.size();
            if (st.tokens != tokens || st.distinct != distinct || (payload.size() && st.width != width) || got != blobBytes || str(p2b::decodeBlob(*v, blob)) != payload) {
               fail("held-out column " + idx + ": Python size model and C++ encoder disagree");
               break;
            }
         } catch (const std::exception& e) {
            fail("held-out column " + idx + ": " + e.what());
            break;
         }
         ++heldoutRows;
      }
   }

   std::ostringstream js;
   js << "{\n  \"ok\": " << (failures.empty() ? "true" : "false") << ",\n  \"file\": \"" << jsonEscape(path) << "\",\n  \"entries\": " << v->size()
      << ",\n  \"file_bytes\": " << raw.size() << ",\n  \"sha256\": \"" << sha << "\",\n  \"table_id_hex\": \"" << tableId << "\",\n  \"length_histogram\": {";
   bool first = true;
   for (auto [len, n] : lengths) {
      js << (first ? "" : ", ") << "\"" << len << "\": " << n;
      first = false;
   }
   js << "},\n  \"layout_checked\": " << (p2aPath.empty() ? "false" : "true") << ",\n  \"learned_hi\": " << learnedHi << ",\n  \"learned_kn\": " << learnedKn
      << ",\n  \"ascii_entries\": " << asciiEntries << ",\n  \"entry_round_trips\": " << roundTrips << ",\n  \"mixed_round_trips\": " << mixedRoundTrips
      << ",\n  \"heldout_rows_checked\": " << heldoutRows << ",\n  \"failures\": [";
   for (size_t i = 0; i < failures.size(); ++i) js << (i ? ", " : "") << "\"" << jsonEscape(failures[i]) << "\"";
   js << "]\n}\n";
   std::cout << js.str();
   if (!jsonOut.empty()) std::ofstream(jsonOut) << js.str();
   return failures.empty() ? 0 : 1;
}
