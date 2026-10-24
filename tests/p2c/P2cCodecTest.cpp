// P2c tests: the P2b codec (HCC1 codec 3, unchanged) with a P2c-layout vocabulary.
// The vocabulary is built at build time from the SYNTHETIC unit-test fixture (tests/p2c/fixtures/make_synthetic_corpus.py,
// meaningless pseudo-words). It is a test vocabulary only: nothing here measures compression effectiveness.
#include "catch2/catch_test_macros.hpp"
#include "column_format.hpp"
#include "p2b_codec.hpp"
#include <fstream>
#include <map>
#include <set>
#include <sstream>
#include <string>
#include <vector>
//---------------------------------------------------------------------------
using namespace hashcode;
//---------------------------------------------------------------------------
namespace {
//---------------------------------------------------------------------------
constexpr size_t coreEntries = 5248;  // P2a IDs 0-5,247
//---------------------------------------------------------------------------
const p1::Vocabulary& p2c() {
   static const p1::Vocabulary v(HASHCODE_P2C_FIXTURE_VOCABULARY);
   return v;
}
const p1::Vocabulary& p2a() {
   static const p1::Vocabulary v(HASHCODE_P2A_VOCABULARY);
   return v;
}
//---------------------------------------------------------------------------
std::span<const std::byte> bytes(const std::string& s) { return {reinterpret_cast<const std::byte*>(s.data()), s.size()}; }
std::string str(const std::vector<std::byte>& b) { return std::string(reinterpret_cast<const char*>(b.data()), b.size()); }
//---------------------------------------------------------------------------
bool isAscii(const std::string& e) {
   for (unsigned char c : e)
      if (c >= 128) return false;
   return true;
}
/// Learned entries: from ID 5,248 up to the first all-ASCII entry.
size_t learnedEnd() {
   size_t i = coreEntries;
   while (i < p2c().size() && !isAscii(p2c().entry(static_cast<uint16_t>(i)))) ++i;
   return i;
}
//---------------------------------------------------------------------------
std::string roundTrip(const p1::Vocabulary& v, const std::string& s, p2b::Stats& st) {
   auto blob = p2b::encodeBlob(v, bytes(s), st);
   REQUIRE(blob.size() == st.mappingBytes + st.tokenBytes + p2b::footerBytes);
   return str(p2b::decodeBlob(v, blob));
}
//---------------------------------------------------------------------------
std::vector<std::byte> tamper(std::vector<std::byte> b, size_t i, std::byte v) {
   b.at(i) = v;
   return b;
}
//---------------------------------------------------------------------------
/// Reference greedy longest prefix over the entry list (no hash maps), for cross-checking Vocabulary::tokenize.
std::vector<uint16_t> naiveTokenize(const p1::Vocabulary& v, const std::string& s) {
   static std::map<std::string, uint16_t> index;
   if (index.empty())
      for (size_t i = 0; i < v.size(); ++i) index.emplace(v.entry(static_cast<uint16_t>(i)), static_cast<uint16_t>(i));
   std::vector<uint16_t> out;
   size_t pos = 0;
   while (pos < s.size()) {
      for (size_t len = std::min<size_t>(16, s.size() - pos); len >= 1; --len) {
         auto it = index.find(s.substr(pos, len));
         if (it != index.end()) {
            out.push_back(it->second);
            pos += len;
            break;
         }
      }
   }
   return out;
}
//---------------------------------------------------------------------------
std::string unhex(const std::string& h) {
   std::string out;
   for (size_t i = 0; i + 1 < h.size(); i += 2) out.push_back(static_cast<char>(std::stoi(h.substr(i, 2), nullptr, 16)));
   return out;
}
//---------------------------------------------------------------------------
}
//---------------------------------------------------------------------------
TEST_CASE("P2c fixture vocabulary: layout, size and identity", "[p2c]") {
   REQUIRE(p2c().size() == 65536);
   std::ifstream shaFile(HASHCODE_P2C_FIXTURE_SHA256);
   std::string sha;
   shaFile >> sha;
   REQUIRE(sha.size() == 64);
   std::string idHex;
   for (auto b : p2c().tableId()) {
      char buf[3];
      std::snprintf(buf, sizeof buf, "%02x", b);
      idHex += buf;
   }
   CHECK(idHex == sha.substr(0, 16));
   CHECK(p2c().tableId() != p2a().tableId());
   for (size_t i = 0; i < coreEntries; ++i) REQUIRE(p2c().entry(static_cast<uint16_t>(i)) == p2a().entry(static_cast<uint16_t>(i)));
   const size_t end = learnedEnd();
   REQUIRE(end > coreEntries);
   std::set<std::string> p2aEntries;
   for (size_t i = 0; i < p2a().size(); ++i) p2aEntries.insert(p2a().entry(static_cast<uint16_t>(i)));
   for (size_t i = coreEntries; i < end; ++i) {
      const auto& e = p2c().entry(static_cast<uint16_t>(i));
      CHECK(e.size() <= 16);
      CHECK(e.size() >= 6);  // at least two Indic code points
      CHECK(!p2aEntries.count(e));
   }
   // ASCII tail: P2a's ASCII entries in order, truncated.
   for (size_t i = end, j = coreEntries; i < p2c().size(); ++i, ++j) REQUIRE(p2c().entry(static_cast<uint16_t>(i)) == p2a().entry(static_cast<uint16_t>(j)));
}
//---------------------------------------------------------------------------
TEST_CASE("P2c greedy matching prefers longer learned entries", "[p2c]") {
   const size_t end = learnedEnd();
   size_t checked = 0;
   for (size_t i = coreEntries; i < end; i += 97) {
      const auto& e = p2c().entry(static_cast<uint16_t>(i));
      size_t fb = 0;
      auto ids = p2c().tokenize(bytes(e), fb);
      // A learned entry tokenizes to itself, unless an even longer entry is a prefix-match of it (impossible: same bytes).
      REQUIRE(ids.size() == 1);
      CHECK(ids[0] == i);
      CHECK(p2a().tokenize(bytes(e), fb).size() > 1);
      ++checked;
   }
   CHECK(checked > 10);
   // Overlapping candidates: entry + entry and entry cut mid-way agree with the reference greedy implementation.
   for (size_t i = coreEntries; i + 1 < end; i += 131) {
      const auto& a = p2c().entry(static_cast<uint16_t>(i));
      const auto& b = p2c().entry(static_cast<uint16_t>(i + 1));
      for (const std::string& s : {a + b, b + a, a.substr(3) + b, a + " " + b, " " + a + b.substr(0, b.size() - 1)}) {
         size_t fb = 0;
         CHECK(p2c().tokenize(bytes(s), fb) == naiveTokenize(p2c(), s));
      }
   }
}
//---------------------------------------------------------------------------
TEST_CASE("P2c round trips are exact", "[p2c]") {
   std::string all;
   for (int b = 0; b < 256; ++b) all.push_back(static_cast<char>(b));
   const std::string learned = p2c().entry(static_cast<uint16_t>(coreEntries)) + p2c().entry(static_cast<uint16_t>(learnedEnd() - 1));
   const std::vector<std::string> cases = {
      "", " ", "a", std::string(1, '\0'), std::string("a\0b\0", 4), "\n", "\r\n", "\r", "\t", "line1\nline2\r\n\tend",
      "नमस्ते दुनिया", "ಕನ್ನಡ ಭಾಷೆ", "hello, world 123", "मिश्रित ಮಿಶ್ರ mixed text", "\U0001F600\U0001F44D‍\U0001F525 ₹100",
      "क्‍ष ಕ್‌ಷ", "\xff\xfe\x80 invalid \xe0\xa4", all, learned, learned + learned + "x" + learned,
      "   " + learned + "  ", std::string(5000, 'a'),
   };
   for (const auto& s : cases) {
      p2b::Stats st;
      CHECK(roundTrip(p2c(), s, st) == s);
   }
   // Every prefix cut of a mixed string, including cuts inside code points and aksharas.
   const std::string mixed = learned + " नमस्ते ಕನ್ನಡ\0x\n" + learned.substr(0, 7);
   for (size_t n = 0; n <= mixed.size(); ++n) {
      p2b::Stats st;
      REQUIRE(roundTrip(p2c(), mixed.substr(0, n), st) == mixed.substr(0, n));
   }
   // Long repetitive input uses 1-byte local IDs.
   std::string rep;
   for (int i = 0; i < 400; ++i) rep += learned + " ";
   p2b::Stats st;
   CHECK(roundTrip(p2c(), rep, st) == rep);
   CHECK(st.width == 1);
}
//---------------------------------------------------------------------------
TEST_CASE("P2c fallback is byte exact and counted", "[p2c]") {
   p2b::Stats st;
   const std::string s = "\xff\xfe\x80";
   CHECK(roundTrip(p2c(), s, st) == s);
   CHECK(st.tokens == 3);
   CHECK(st.fallbackTokens == 3);
}
//---------------------------------------------------------------------------
TEST_CASE("P2c and P2a/P2b blobs are not interchangeable", "[p2c]") {
   const std::string s = p2c().entry(static_cast<uint16_t>(coreEntries)) + " text";
   p2b::Stats st;
   auto c = p2b::encodeBlob(p2c(), bytes(s), st);
   CHECK_THROWS(p2b::decodeBlob(p2a(), c));  // different table ID in the BTT2 footer
   auto b = p2b::encodeBlob(p2a(), bytes(s), st);
   CHECK_THROWS(p2b::decodeBlob(p2c(), b));
   size_t tokens = 0, fallback = 0;
   CHECK_THROWS(p2b::decodeBlob(p2c(), p1::encodeBlob(p2c(), bytes(s), tokens, fallback)));  // BTT1 footer is not BTT2
   CHECK(str(p2b::decodeBlob(p2c(), c)) == s);
}
//---------------------------------------------------------------------------
TEST_CASE("P2c decoder rejects malformed blobs", "[p2c]") {
   const std::string e = p2c().entry(static_cast<uint16_t>(coreEntries));
   std::string s;
   for (int i = 0; i < 20; ++i) s += e + " ";
   p2b::Stats st;
   auto narrow = p2b::encodeBlob(p2c(), bytes(s), st);
   REQUIRE(st.width == 1);
   const size_t footer = narrow.size() - p2b::footerBytes;
   CHECK_THROWS(p2b::decodeIds(p2c(), tamper(narrow, 0, std::byte{3})));
   CHECK_THROWS(p2b::decodeIds(p2c(), tamper(narrow, 1, std::byte{0})));
   CHECK_THROWS(p2b::decodeIds(p2c(), tamper(narrow, st.mappingBytes, std::byte{static_cast<uint8_t>(st.distinct)})));  // local ID == m
   CHECK_THROWS(p2b::decodeIds(p2c(), tamper(narrow, footer, std::byte{'X'})));
   CHECK_THROWS(p2b::decodeIds(p2c(), tamper(narrow, footer + 4, std::byte{2})));
   CHECK_THROWS(p2b::decodeIds(p2c(), tamper(narrow, narrow.size() - 1, narrow.back() ^ std::byte{1})));  // wrong vocabulary ID
   for (size_t n = 0; n < narrow.size(); ++n) CHECK_THROWS(p2b::decodeIds(p2c(), std::span<const std::byte>(narrow.data(), n)));
   p2b::Stats wst;
   auto wide = p2b::encodeBlob(p2c(), bytes(e), wst);
   REQUIRE(wst.width == 2);
   auto odd = wide;
   odd.insert(odd.begin() + 1, std::byte{0});
   CHECK_THROWS(p2b::decodeIds(p2c(), odd));
   // Every 16-bit value is a valid global ID in a 65,536-entry vocabulary: 0xFFFF must decode to the last entry, not read out of bounds.
   auto maxId = tamper(tamper(wide, 1, std::byte{0xFF}), 2, std::byte{0xFF});
   auto ids = p2b::decodeIds(p2c(), maxId);
   REQUIRE(ids.size() == 1);
   CHECK(ids[0] == 0xFFFF);
   CHECK(str(p2b::decodeBlob(p2c(), maxId)) == p2c().entry(0xFFFF));
}
//---------------------------------------------------------------------------
TEST_CASE("P2c inside HCC1 keeps boundaries; reported sizes equal serialized sizes", "[p2c][column]") {
   const std::string l = p2c().entry(static_cast<uint16_t>(coreEntries));
   // A learned entry split across two values must not be matched across the boundary in the reconstruction.
   const std::vector<std::string> values = {"", l.substr(0, 6), l.substr(6), "", std::string("x\0y", 3), "line\r\n\tನ", " " + l, "\U0001F600", ""};
   for (int reps : {1, 40}) {
      std::vector<std::string> column;
      for (int r = 0; r < reps; ++r) column.insert(column.end(), values.begin(), values.end());
      auto payload = column::concatenate(column);
      p2b::Stats st;
      auto blob = p2b::encodeBlob(p2c(), payload.bytes(), st);
      column::Layout layout;
      auto container = column::serialize(column::Codec::P2b, column, blob, layout);
      CHECK(layout.header + layout.boundary + st.mappingBytes + st.tokenBytes + p2b::footerBytes == container.size());
      auto parsed = column::parse(container);
      REQUIRE(parsed.codec == column::Codec::P2b);
      CHECK(column::split(p2b::decodeBlob(p2c(), parsed.blob), parsed.lengths) == column);
   }
   // Empty payload: no codec call, no blob.
   column::Layout layout;
   auto container = column::serialize(column::Codec::P2b, {"", ""}, {}, layout);
   CHECK(container.size() == layout.header + layout.boundary);
   CHECK(column::split({}, column::parse(container).lengths) == std::vector<std::string>{"", ""});
}
//---------------------------------------------------------------------------
TEST_CASE("P2c builder's Python size model matches the C++ P2b encoder on the held-out fixture columns", "[p2c]") {
   std::ifstream in(HASHCODE_P2C_FIXTURE_HELDOUT_CHECK);
   REQUIRE(in);
   std::string line;
   std::getline(in, line);  // header
   size_t rows = 0;
   while (std::getline(in, line)) {
      std::istringstream f(line);
      std::string idx, hexPayload;
      size_t tokens, distinct, width, blobBytes;
      std::getline(f, idx, '\t');
      std::getline(f, hexPayload, '\t');
      f >> tokens >> distinct >> width >> blobBytes;
      const auto payload = unhex(hexPayload);
      p2b::Stats st;
      auto blob = p2b::encodeBlob(p2c(), bytes(payload), st);
      CHECK(st.tokens == tokens);
      CHECK(st.distinct == distinct);
      CHECK(st.width == width);
      CHECK(blob.size() == blobBytes);
      CHECK(str(p2b::decodeBlob(p2c(), blob)) == payload);
      ++rows;
   }
   CHECK(rows >= 1);
}
//---------------------------------------------------------------------------
