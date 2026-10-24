#include "catch2/catch_test_macros.hpp"
#include "compressor/Compressor.hpp"
#include "tokenizer/Tokenizer.hpp"
#include "tokenizer/TokenizerConfig.hpp"
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <exception>
#include <optional>
#include <random>
#include <span>
#include <string>
#include <string_view>
#include <utility>
#include <vector>
//---------------------------------------------------------------------------
using namespace sgtt;
//---------------------------------------------------------------------------
namespace {
//---------------------------------------------------------------------------
struct Input {
   std::string name;
   std::string bytes;
};
//---------------------------------------------------------------------------
struct Config {
   std::string name;
   compressor::CompressorConfig config;
};
//---------------------------------------------------------------------------
std::string bytesOf(const char* data, size_t size) { return std::string(data, size); }
//---------------------------------------------------------------------------
std::string repeat(std::string_view unit, size_t minBytes) {
   std::string result;
   while (result.size() < minBytes) result += unit;
   return result;
}
//---------------------------------------------------------------------------
const std::string& mixedParagraph() {
   static const std::string text =
      "Order #42: पनीर टिक्का ×2 — ₹350 "
      "(ಕನ್ನಡ/தமிழ்/తెలుగు) \U0001F600\n"
      "id=7,name='ರಾಮ್ Ram राम',city=\"Chennai சென்னை\"\r\n";
   return text;
}
//---------------------------------------------------------------------------
std::vector<Input> fixedInputs() {
   std::vector<Input> inputs = {
      // ASCII
      {"ascii single byte", "a"},
      {"ascii pangram", "The quick brown fox jumps over the lazy dog."},
      {"ascii punctuation and whitespace", " \t\n\r\n  !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~ "},
      {"ascii digits", "0123456789 3.14159 -42 1e10"},
      {"crlf lines", "line1\r\nline2\r\n\r\n"},
      // Indian scripts
      {"hindi devanagari", "नमस्ते दुनिया। भारत एक विशाल देश है।"},
      {"bengali", "আমি বাংলায় গান গাই। কলকাতা"},
      {"tamil", "வணக்கம் உலகம். தமிழ் ஒரு செம்மொழி."},
      {"telugu", "తెలుగు భాష చాలా మధురమైనది. హైదరాబాద్"},
      {"kannada", "ಕನ್ನಡ ನಾಡು ನುಡಿ. ಬೆಂಗಳೂರು ಕರ್ನಾಟಕದ ರಾಜಧಾನಿ."},
      {"malayalam", "മലയാളം ഒരു ദ്രാവിഡ ഭാഷയാണ്. കേരളം"},
      {"gujarati", "ગુજરાતી ભાષા"},
      {"gurmukhi", "ਪੰਜਾਬੀ ਭਾਸ਼ਾ"},
      {"odia", "ଓଡ଼ିଆ ଭାଷା"},
      {"indic digits", "०१२३४५६७८९ ০১২ ௧௨௩ ౧౨౩ ೧೨೩ ൧൨൩"},
      // Mixed scripts
      {"mixed scripts, digits, currency, emoji", mixedParagraph()},
      // Combining marks, viramas, joiners
      {"devanagari conjunct with virama", "क्ष"},
      {"trailing virama", "क्"},
      {"virama + zwj", "क्‍ष"},
      {"virama + zwnj", "क्‌ष"},
      {"malayalam atomic chillu", "ൽ"},
      {"malayalam legacy chillu (virama + zwj)", "ല്‍"},
      {"nukta precomposed", "क़"},
      {"nukta decomposed", "क़"},
      {"bengali khanda ta", "ৎ"},
      {"bengali ya-phala with zwnj", "র‌্য"},
      {"kannada conjunct", "ಕ್ಷ"},
      {"tamil pulli", "க்"},
      {"telugu conjunct", "క్ష"},
      {"leading combining mark", "ि"},
      {"stacked combining marks", "कििंँ"},
      {"dotted circle base", "◌ि"},
      {"bom, nbsp, soft hyphen", "﻿ ­"},
      {"emoji zwj sequence", "\U0001F469‍\U0001F4BB"},
      // Invalid UTF-8 and raw bytes
      {"invalid: ff fe", "\xFF\xFE"},
      {"invalid: truncated 3-byte sequence", "\xE0\xA4"},
      {"invalid: overlong encoding", "\xC0\xAF"},
      {"invalid: encoded surrogate", "\xED\xA0\x80"},
      {"invalid: lone continuation bytes", "\x80\x80\x80"},
      {"invalid: above U+10FFFF", "\xF4\x90\x80\x80"},
      {"invalid utf-8 inside indic text", "ಕ\xFFನ\xE0\xA4" "a"},
      {"single NUL", bytesOf("\0", 1)},
      {"two NULs (token removed from OpenAI200K dict)", bytesOf("\0\0", 2)},
      {"NUL inside text", bytesOf("a\0b\0\0c", 6)},
      {"three NULs inside text", bytesOf("abcdefgh\0\0\0ijklmnop", 19)},
      {"two trailing NULs", bytesOf("abcdefghij\0\0", 12)},
      // Repetition
      {"repeated ascii byte", std::string(10000, 'a')},
      {"repeated kannada letter", repeat("ಅ", 10000)},
   };
   std::string all;
   for (int i = 0; i < 256; ++i) all.push_back(static_cast<char>(i));
   inputs.push_back({"all 256 byte values", all});
   inputs.push_back({"all 256 byte values, reversed", std::string(all.rbegin(), all.rend())});
   return inputs;
}
//---------------------------------------------------------------------------
std::vector<Input> boundaryInputs() {
   std::vector<Input> inputs;
   const std::string base = mixedParagraph() + "ಕನ್ನಡ ನಾಡು";
   for (size_t length = 1; length <= base.size(); ++length) {
      inputs.push_back({"mixed-script prefix of " + std::to_string(length) + " bytes", base.substr(0, length)});
   }
   std::mt19937_64 rng(20261024);
   auto randomBytes = [&](size_t length) {
      std::string s(length, '\0');
      for (auto& c : s) c = static_cast<char>(rng() & 0xFF);
      return s;
   };
   for (size_t length = 1; length <= 256; ++length) {
      inputs.push_back({"random bytes, length " + std::to_string(length), randomBytes(length)});
   }
   inputs.push_back({"random bytes, length 4096", randomBytes(4096)});
   return inputs;
}
//---------------------------------------------------------------------------
std::vector<Input> longInputs() {
   return {
      {"mixed-script text, >= 1 MiB", repeat(mixedParagraph(), 1 << 20)},
      {"kannada text, >= 1 MiB", repeat("ಕನ್ನಡ ನಾಡು ನುಡಿ. ", 1 << 20)},
   };
}
//---------------------------------------------------------------------------
Config sgttConfig(tokenizer::TokenizerType type, tokenizer::TokenIdEncoding encoding) {
   tokenizer::TokenizerConfig tc{.tokenizer = type, .tokenIdEncoding = encoding};
   return {"sgtt tokenizer=" + tokenizer::toString(type) + " encoding=" + tokenizer::toString(encoding), {compressor::parseCompressor("sgtt"), std::nullopt, compressor::OnPairConfig{false, false}, tc}};
}
//---------------------------------------------------------------------------
Config tok() {
   return {"tok", {compressor::parseCompressor("tok"), std::nullopt, compressor::OnPairConfig{false, false}, {}}};
}
//---------------------------------------------------------------------------
std::vector<tokenizer::TokenizerType> tokenizerRange(tokenizer::TokenizerType first, tokenizer::TokenizerType last) {
   std::vector<tokenizer::TokenizerType> types;
   for (unsigned t = first; t <= static_cast<unsigned>(last); ++t) types.push_back(static_cast<tokenizer::TokenizerType>(t));
   return types;
}
//---------------------------------------------------------------------------
constexpr tokenizer::TokenIdEncoding allEncodings[] = {tokenizer::SparseIds, tokenizer::DenseIds, tokenizer::FrequentIds};
//---------------------------------------------------------------------------
std::vector<std::byte> roundTrip(const compressor::CompressorConfig& config, std::string_view data) {
   // Same buffer contract as upstream test/Tester.hpp: 16 zero bytes after the input, 10x compressed buffer, 2x decode buffer.
   std::vector<std::byte> padded(data.size() + 16, std::byte{0});
   std::memcpy(padded.data(), data.data(), data.size());
   std::vector<std::byte> compressed(10 * data.size());
   compressor::Compressor::create(config)->compress(std::span(padded.data(), data.size()), compressed);

   auto decompressor = compressor::Compressor::create(config, compressed);
   std::vector<std::byte> decoded(2 * decompressor->getUncompressedSize(compressed));
   std::vector<std::vector<std::byte>> temporaryBuffers;
   decompressor->decompress(compressed, decoded, temporaryBuffers);
   return decoded;
}
//---------------------------------------------------------------------------
void checkRoundTrip(const Config& config, const Input& input) {
   INFO("config: " << config.name);
   INFO("input: " << input.name << " (" << input.bytes.size() << " bytes)");
   std::vector<std::byte> decoded;
   try {
      decoded = roundTrip(config.config, input.bytes);
   } catch (const std::exception& e) {
      FAIL_CHECK("round trip threw: " << e.what());
      return;
   }
   const size_t common = std::min(decoded.size(), input.bytes.size());
   size_t firstMismatch = common;
   for (size_t i = 0; i < common; ++i) {
      if (decoded[i] != static_cast<std::byte>(input.bytes[i])) {
         firstMismatch = i;
         break;
      }
   }
   INFO("decoded size: " << decoded.size() << ", first mismatching byte offset: " << firstMismatch);
   CHECK(decoded.size() == input.bytes.size());
   CHECK(firstMismatch == common);
}
//---------------------------------------------------------------------------
void checkAll(const std::vector<Config>& configs, const std::vector<Input>& inputs) {
   for (const auto& config : configs)
      for (const auto& input : inputs)
         checkRoundTrip(config, input);
}
//---------------------------------------------------------------------------
std::vector<Config> baseTokenizerConfigs() {
   std::vector<Config> configs;
   for (auto type : tokenizerRange(tokenizer::Claude, tokenizer::OpenAI200K))
      for (auto encoding : allEncodings)
         configs.push_back(sgttConfig(type, encoding));
   return configs;
}
//---------------------------------------------------------------------------
std::vector<Config> representativeConfigs() {
   return {
      sgttConfig(tokenizer::OpenAI200K, tokenizer::SparseIds),
      sgttConfig(tokenizer::OpenAI200K, tokenizer::DenseIds),
      sgttConfig(tokenizer::Gemma3, tokenizer::DenseIds),
      sgttConfig(tokenizer::Llama3, tokenizer::FrequentIds),
      tok(),
   };
}
//---------------------------------------------------------------------------
}
//---------------------------------------------------------------------------
TEST_CASE("sgtt round trip: base tokenizers x id encodings", "[roundtrip][sgtt]") {
   checkAll(baseTokenizerConfigs(), fixedInputs());
}
//---------------------------------------------------------------------------
TEST_CASE("sgtt round trip: patched and random tokenizer variants", "[roundtrip][sgtt][variants]") {
   std::vector<Config> configs;
   for (auto type : tokenizerRange(tokenizer::ClaudePatched, tokenizer::OpenAI200KRandom))
      for (auto encoding : allEncodings)
         configs.push_back(sgttConfig(type, encoding));
   checkAll(configs, fixedInputs());
}
//---------------------------------------------------------------------------
TEST_CASE("sgtt round trip: max token sizes", "[roundtrip][sgtt][tokensize]") {
   std::vector<Config> configs;
   for (unsigned size = 1; size <= 16; ++size) {
      for (auto encoding : allEncodings) {
         auto config = sgttConfig(tokenizer::OpenAI200K, encoding);
         config.config.tokenizerConfig.maxTokenSize = static_cast<tokenizer::TokenSize>(size);
         config.name += " maxTokenSize=" + std::to_string(size);
         configs.push_back(config);
      }
   }
   checkAll(configs, fixedInputs());
}
//---------------------------------------------------------------------------
TEST_CASE("sgtt round trip: Huffman token compressor", "[roundtrip][sgtt][huffman]") {
   std::vector<Config> configs;
   for (auto type : {tokenizer::OpenAI50K, tokenizer::OpenAI100K, tokenizer::OpenAI200K}) {
      auto config = sgttConfig(type, tokenizer::DenseIds);
      config.config.tokenizerConfig.tokenCompressor = {.compressor = compressor::CompressorType::Huffman};
      config.name += " tokencompression=huffman";
      configs.push_back(config);
   }
   checkAll(configs, fixedInputs());
}
//---------------------------------------------------------------------------
TEST_CASE("tok round trip", "[roundtrip][tok]") {
   checkAll({tok()}, fixedInputs());
}
//---------------------------------------------------------------------------
TEST_CASE("round trip: token-boundary and random inputs", "[roundtrip][boundary]") {
   checkAll(representativeConfigs(), boundaryInputs());
}
//---------------------------------------------------------------------------
TEST_CASE("round trip: long inputs", "[roundtrip][long]") {
   auto configs = representativeConfigs();
   for (auto type : tokenizerRange(tokenizer::Claude, tokenizer::OpenAI200K)) configs.push_back(sgttConfig(type, tokenizer::DenseIds));
   checkAll(configs, longInputs());
}
//---------------------------------------------------------------------------
namespace {
//---------------------------------------------------------------------------
/// Byte value v appears v + 1 times, so all frequencies differ and the frequency order has no ties.
std::string unevenByteValues(std::optional<unsigned> omittedValue) {
   std::string s;
   for (unsigned v = 0; v < 256; ++v) {
      if (omittedValue && v == *omittedValue) continue;
      s.append(v + 1, static_cast<char>(v));
   }
   return s;
}
//---------------------------------------------------------------------------
size_t infoField(const std::string& info, const std::string& key) {
   auto pos = info.find(key + ": ");
   REQUIRE(pos != std::string::npos);
   return std::stoull(info.substr(pos + key.size() + 2));
}
//---------------------------------------------------------------------------
/// Encode with the tokenizer directly to observe how many vocabulary entries the input uses.
std::pair<size_t, size_t> usedAndAvailableTokens(const tokenizer::TokenizerConfig& config, const std::string& bytes) {
   auto t = tokenizer::Tokenizer::create(config.tokenizer, config);
   std::vector<std::byte> padded(bytes.size() + 16, std::byte{0});
   std::memcpy(padded.data(), bytes.data(), bytes.size());
   t->encode(std::span(padded.data(), bytes.size()));
   const auto info = t->getInfo();
   INFO("tokenizer info: " << info);
   return {infoField(info, "used_tokens"), infoField(info, "available_tokens")};
}
//---------------------------------------------------------------------------
}
//---------------------------------------------------------------------------
TEST_CASE("FrequentIds maxTokenSize=1: full vs partial vocabulary", "[roundtrip][frequent][vocab]") {
   auto config = sgttConfig(tokenizer::OpenAI200K, tokenizer::FrequentIds);
   config.config.tokenizerConfig.maxTokenSize = tokenizer::Token1;
   config.name += " maxTokenSize=1";

   SECTION("all 256 byte values, uneven frequencies (used == available)") {
      const Input input{"all 256 byte values, frequency v+1", unevenByteValues(std::nullopt)};
      REQUIRE(input.bytes.size() == 256 * 257 / 2);
      auto [used, available] = usedAndAvailableTokens(config.config.tokenizerConfig, input.bytes);
      CHECK(available == 256);
      CHECK(used == available);
      checkRoundTrip(config, input);
   }
   SECTION("255 byte values, 0x80 omitted (used < available)") {
      const Input input{"255 byte values without 0x80, frequency v+1", unevenByteValues(0x80u)};
      REQUIRE(input.bytes.size() == 256 * 257 / 2 - (0x80 + 1));
      REQUIRE(input.bytes.find(static_cast<char>(0x80)) == std::string::npos);
      auto [used, available] = usedAndAvailableTokens(config.config.tokenizerConfig, input.bytes);
      CHECK(available == 256);
      CHECK(used == 255);
      checkRoundTrip(config, input);
   }
}
//---------------------------------------------------------------------------
TEST_CASE("round trip: empty input", "[roundtrip][empty]") {
   auto configs = baseTokenizerConfigs();
   configs.push_back(tok());
   // One section per config so a crash can be isolated with `-c "<config name>"`.
   for (const auto& config : configs) {
      DYNAMIC_SECTION(config.name) {
         checkRoundTrip(config, {"empty string", ""});
      }
   }
}
//---------------------------------------------------------------------------
