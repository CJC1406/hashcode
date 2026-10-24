#include "catch2/catch_test_macros.hpp"
#include "column_format.hpp"
#include "p2b_codec.hpp"
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>
//---------------------------------------------------------------------------
using namespace hashcode;
//---------------------------------------------------------------------------
namespace {
//---------------------------------------------------------------------------
const p1::Vocabulary& vocab() {
   static const p1::Vocabulary v(HASHCODE_P2A_VOCABULARY);
   return v;
}
//---------------------------------------------------------------------------
std::span<const std::byte> bytes(const std::string& s) { return {reinterpret_cast<const std::byte*>(s.data()), s.size()}; }
//---------------------------------------------------------------------------
std::string str(const std::vector<std::byte>& b) { return std::string(reinterpret_cast<const char*>(b.data()), b.size()); }
//---------------------------------------------------------------------------
std::string roundTrip(const std::string& s, p2b::Stats& st) {
   auto blob = p2b::encodeBlob(vocab(), bytes(s), st);
   REQUIRE(blob.size() == st.mappingBytes + st.tokenBytes + p2b::footerBytes);
   return str(p2b::decodeBlob(vocab(), blob));
}
//---------------------------------------------------------------------------
/// k distinct 6-byte akshara entries (consonant + sign/nukta), each repeated `reps` times, concatenated.
std::string distinctAkshara(size_t k, size_t reps) {
   std::vector<std::string> picked;
   for (uint32_t id = 256; id < 2752 && picked.size() < k; ++id) {
      const auto& e = vocab().entry(static_cast<uint16_t>(id));
      if (e.size() == 6) picked.push_back(e);
   }
   REQUIRE(picked.size() == k);
   std::string s;
   for (size_t r = 0; r < reps; ++r)
      for (const auto& e : picked) s += e;
   return s;
}
//---------------------------------------------------------------------------
std::vector<std::byte> tamper(std::vector<std::byte> b, size_t pos, std::byte value) {
   b[pos] = value;
   return b;
}
//---------------------------------------------------------------------------
}
//---------------------------------------------------------------------------
TEST_CASE("P2b round trip is exact", "[p2b]") {
   std::string all;
   for (int i = 0; i < 256; ++i) all.push_back(static_cast<char>(i));
   const std::vector<std::pair<std::string, std::string>> cases = {
      {"empty", ""},
      {"ascii", "The quick brown fox jumps over the lazy dog."},
      {"hindi", "आज मौसम बहुत सुहावना है।"},
      {"kannada", "ಇಂದು ಹವಾಮಾನ ತುಂಬಾ"},
      {"mixed", "Order #A1023 का delivery ತಲುಪಿದೆ"},
      {"NUL", std::string("\0a\0\0 b\0", 7)},
      {"LF CR CRLF tab", "a\nb\rc\r\nd\te"},
      {"emoji and multibyte", "\U0001F469‍\U0001F4BB ₹350 क़ क़"},
      {"invalid UTF-8", "\xFF\xFE\xE0\xA4 \xC0\xAF"},
      {"all 256 byte values", all},
      {"repetitive", std::string(5000, 'a') + distinctAkshara(10, 50)},
   };
   for (const auto& [name, s] : cases) {
      INFO(name);
      p2b::Stats st;
      CHECK(roundTrip(s, st) == s);
   }
}
//---------------------------------------------------------------------------
TEST_CASE("P2b width rule at 1, 255, 256 and 257 distinct IDs", "[p2b]") {
   for (size_t k : {1u, 255u, 256u, 257u}) {
      INFO("distinct " << k);
      p2b::Stats st;
      const auto s = distinctAkshara(k, 4);
      REQUIRE(roundTrip(s, st) == s);
      CHECK(st.distinct == k);
      CHECK(st.tokens == 4 * k);
      CHECK(st.width == (k <= 256 ? 1u : 2u));
      if (st.width == 1) {
         CHECK(st.mappingBytes == 1 + p2b::varintBytes(k) + 2 * k);
         CHECK(st.tokenBytes == st.tokens);
      } else {
         CHECK(st.mappingBytes == 1);
         CHECK(st.tokenBytes == 2 * st.tokens);
      }
   }
}
//---------------------------------------------------------------------------
TEST_CASE("P2b uses 2-byte IDs when a mapping would not pay off", "[p2b]") {
   // 5 distinct tokens used once: 1 + 1 + 10 + 5 = 17 > 1 + 10, so width 2.
   p2b::Stats st;
   const auto s = distinctAkshara(5, 1);
   CHECK(roundTrip(s, st) == s);
   CHECK(st.distinct == 5);
   CHECK(st.width == 2);
   // The same 5 tokens used 4 times: 1 + 1 + 10 + 20 = 32 < 1 + 40, so width 1.
   p2b::Stats st4;
   CHECK(roundTrip(distinctAkshara(5, 4), st4) == distinctAkshara(5, 4));
   CHECK(st4.width == 1);
}
//---------------------------------------------------------------------------
TEST_CASE("P2b mapping is sorted, deterministic and independent of first-use order", "[p2b]") {
   const std::string a = distinctAkshara(3, 1), forward = a + a + a + a;
   std::vector<std::string> parts;
   for (size_t i = 0; i < 3; ++i) parts.push_back(a.substr(6 * i, 6));
   const std::string backward = parts[2] + parts[1] + parts[0] + parts[2] + parts[1] + parts[0] + parts[2] + parts[1] + parts[0] + parts[2] + parts[1] + parts[0];
   p2b::Stats s1, s2, s3;
   auto b1 = p2b::encodeBlob(vocab(), bytes(forward), s1);
   auto b2 = p2b::encodeBlob(vocab(), bytes(forward), s2);
   auto b3 = p2b::encodeBlob(vocab(), bytes(backward), s3);
   CHECK(b1 == b2);
   REQUIRE(s1.width == 1);
   REQUIRE(s3.width == 1);
   // Identical mapping section (width byte, count, sorted global IDs) for both orders.
   CHECK(std::vector<std::byte>(b1.begin(), b1.begin() + s1.mappingBytes) == std::vector<std::byte>(b3.begin(), b3.begin() + s3.mappingBytes));
   // Layout: [0] width, [1] varint m (= 3, one byte), [2..] m x u16 LE global IDs.
   REQUIRE(static_cast<uint8_t>(b1[1]) == 3);
   REQUIRE(s1.mappingBytes == 2 + 2 * 3);
   for (size_t j = 0; j + 1 < 3; ++j) {
      const size_t at = 2 + 2 * j;
      const uint16_t prev = static_cast<uint8_t>(b1[at]) | (static_cast<uint8_t>(b1[at + 1]) << 8);
      const uint16_t next = static_cast<uint8_t>(b1[at + 2]) | (static_cast<uint8_t>(b1[at + 3]) << 8);
      CHECK(prev < next);
   }
}
//---------------------------------------------------------------------------
TEST_CASE("P2b decoder rejects malformed blobs", "[p2b]") {
   p2b::Stats st;
   auto narrow = p2b::encodeBlob(vocab(), bytes(distinctAkshara(3, 4)), st);
   REQUIRE(st.width == 1);
   const size_t footer = narrow.size() - p2b::footerBytes;
   CHECK_THROWS(p2b::decodeIds(vocab(), tamper(narrow, 0, std::byte{3})));                       // unknown width
   CHECK_THROWS(p2b::decodeIds(vocab(), tamper(narrow, 1, std::byte{0})));                       // mapping count 0
   CHECK_THROWS(p2b::decodeIds(vocab(), tamper(narrow, st.mappingBytes, std::byte{3})));         // local ID >= m (m = 3)
   auto duplicate = narrow;  // mapping entry 0 := entry 1 (bytes 2-3 := 4-5), so the mapping is not strictly increasing
   duplicate[2] = narrow[4];
   duplicate[3] = narrow[5];
   CHECK_THROWS(p2b::decodeIds(vocab(), duplicate));
   CHECK_THROWS(p2b::decodeIds(vocab(), tamper(narrow, footer, std::byte{'X'})));                // footer magic
   CHECK_THROWS(p2b::decodeIds(vocab(), tamper(narrow, footer + 4, std::byte{2})));              // footer version
   CHECK_THROWS(p2b::decodeIds(vocab(), tamper(narrow, narrow.size() - 1, std::byte{0x55})));    // wrong vocabulary ID
   // Truncated mapping: claim 200 entries in a short blob.
   CHECK_THROWS(p2b::decodeIds(vocab(), tamper(narrow, 1, std::byte{200})));
   CHECK_THROWS(p2b::decodeIds(vocab(), std::span<const std::byte>(narrow.data(), 5)));
   // Odd 2-byte stream.
   p2b::Stats wide;
   auto w = p2b::encodeBlob(vocab(), bytes(distinctAkshara(5, 1)), wide);
   REQUIRE(wide.width == 2);
   w.insert(w.begin() + 1, std::byte{0});
   CHECK_THROWS(p2b::decodeIds(vocab(), w));
   // P1/P2a blobs (BTT1 footer) are not P2b blobs.
   size_t tokens = 0, fallback = 0;
   CHECK_THROWS(p2b::decodeIds(vocab(), p1::encodeBlob(vocab(), bytes("abc"), tokens, fallback)));
}
//---------------------------------------------------------------------------
TEST_CASE("P2b rejects global IDs outside a smaller vocabulary", "[p2b]") {
   // A 266-entry vocabulary (256 single bytes + 10 two-letter entries), written to a temporary file.
   std::string file = "P1V1";
   const uint32_t count = 266;
   for (int i = 0; i < 4; ++i) file.push_back(static_cast<char>((count >> (8 * i)) & 0xFF));
   for (int i = 0; i < 256; ++i) file += std::string{static_cast<char>(1), static_cast<char>(i)};
   for (int i = 0; i < 10; ++i) file += std::string{static_cast<char>(2), static_cast<char>('a' + i), 'z'};
   const auto path = (std::filesystem::temp_directory_path() / "hashcode_p2b_small_vocab.bin").string();
   std::ofstream(path, std::ios::binary) << file;
   const p1::Vocabulary small(path);
   REQUIRE(small.size() == 266);
   p2b::Stats st;
   auto narrow = p2b::encodeBlob(small, bytes("azazazazbzbzbzbz"), st);
   REQUIRE(st.width == 1);
   CHECK(str(p2b::decodeBlob(small, narrow)) == "azazazazbzbzbzbz");
   auto badMap = narrow;
   badMap[2] = std::byte{0x2C};  // first mapped ID -> 300 (0x012C), outside 266 entries
   badMap[3] = std::byte{0x01};
   CHECK_THROWS(p2b::decodeIds(small, badMap));
   p2b::Stats st2;
   auto wide = p2b::encodeBlob(small, bytes("az"), st2);
   REQUIRE(st2.width == 2);
   wide[1] = std::byte{0x2C};
   wide[2] = std::byte{0x01};
   CHECK_THROWS(p2b::decodeIds(small, wide));
   std::filesystem::remove(path);
}
//---------------------------------------------------------------------------
TEST_CASE("P2b inside HCC1 keeps boundaries; reported sizes equal serialized sizes", "[p2b][column]") {
   const std::vector<std::string> values = {"", "नमस्ते दुनिया", "", std::string("x\0y", 3),
                                            "line\r\n\tನ", " ", "\U0001F600", ""};
   for (int reps : {1, 30}) {
      std::vector<std::string> column;
      for (int r = 0; r < reps; ++r) column.insert(column.end(), values.begin(), values.end());
      auto payload = column::concatenate(column);
      p2b::Stats st;
      auto blob = p2b::encodeBlob(vocab(), payload.bytes(), st);
      column::Layout layout;
      auto container = column::serialize(column::Codec::P2b, column, blob, layout);
      CHECK(layout.header + layout.boundary + st.mappingBytes + st.tokenBytes + p2b::footerBytes == container.size());
      auto parsed = column::parse(container);
      REQUIRE(parsed.codec == column::Codec::P2b);
      CHECK(column::split(p2b::decodeBlob(vocab(), parsed.blob), parsed.lengths) == column);
   }
}
//---------------------------------------------------------------------------
