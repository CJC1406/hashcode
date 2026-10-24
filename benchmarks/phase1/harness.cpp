// Phase 1 measurement harness: upstream sgtt (OpenAI200K, Gemma3) vs raw UTF-8 on identical input bytes.
// Input TSV:  sample_id <TAB> utf8_hex            (one sample per line, written by run_benchmark.py)
// Output CSV: raw per-(sample, method) measurements; derived ratios are computed by run_benchmark.py.
// Usage: phase1_harness <input.tsv> <measurements.csv> <artifacts.tsv> <repetitions>
#include "compressor/Compressor.hpp"
#include "tokenizer/TokenizerConfig.hpp"
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <exception>
#include <fstream>
#include <iostream>
#include <optional>
#include <sstream>
#include <string>
#include <vector>
//---------------------------------------------------------------------------
using namespace sgtt;
using Clock = std::chrono::steady_clock;
//---------------------------------------------------------------------------
namespace {
//---------------------------------------------------------------------------
/// Size of the packed tokenizer footer appended by Tokenizer::compress (static_assert in Tokenizer.hpp).
constexpr size_t sgttFooterBytes = 24;
/// Bytes of padding after the input, as in upstream test/Tester.hpp.
constexpr size_t inputPadding = 16;
//---------------------------------------------------------------------------
struct Method {
   std::string name;
   std::string configuration;
   std::optional<compressor::CompressorConfig> config;
};
//---------------------------------------------------------------------------
std::vector<Method> methods() {
   auto sgtt = [](const char* name, tokenizer::TokenizerType type, tokenizer::TokenIdEncoding encoding) {
      tokenizer::TokenizerConfig tc{.tokenizer = type, .tokenIdEncoding = encoding};
      std::string configuration = "compressor=sgtt tokenizer=" + tokenizer::toString(type) + " token_id_encoding=" + tokenizer::toString(encoding) +
         " max_token_size=default(16) token_compression=identity hash_map=default simd=scalar";
      return Method{name, configuration, compressor::CompressorConfig{compressor::parseCompressor("sgtt"), std::nullopt, compressor::OnPairConfig{false, false}, tc}};
   };
   return {
      {"raw_utf8", "uncompressed UTF-8 bytes", std::nullopt},
      sgtt("sgtt_openai200k_dense", tokenizer::OpenAI200K, tokenizer::DenseIds),
      sgtt("sgtt_openai200k_sparse", tokenizer::OpenAI200K, tokenizer::SparseIds),
      sgtt("sgtt_gemma3_dense", tokenizer::Gemma3, tokenizer::DenseIds),
      sgtt("sgtt_gemma3_sparse", tokenizer::Gemma3, tokenizer::SparseIds),
   };
}
//---------------------------------------------------------------------------
uint64_t fnv1a64(const std::byte* data, size_t size) {
   uint64_t h = 0xcbf29ce484222325ull;
   for (size_t i = 0; i < size; ++i) {
      h ^= static_cast<uint8_t>(data[i]);
      h *= 0x100000001b3ull;
   }
   return h;
}
//---------------------------------------------------------------------------
std::string hex(const std::byte* data, size_t size) {
   static const char* digits = "0123456789abcdef";
   std::string s;
   s.reserve(2 * size);
   for (size_t i = 0; i < size; ++i) {
      auto b = static_cast<uint8_t>(data[i]);
      s.push_back(digits[b >> 4]);
      s.push_back(digits[b & 15]);
   }
   return s;
}
//---------------------------------------------------------------------------
std::vector<std::byte> unhex(const std::string& s) {
   if (s.size() % 2) throw std::runtime_error("odd-length hex");
   std::vector<std::byte> out(s.size() / 2);
   for (size_t i = 0; i < out.size(); ++i) out[i] = static_cast<std::byte>(std::stoul(s.substr(2 * i, 2), nullptr, 16));
   return out;
}
//---------------------------------------------------------------------------
std::optional<uint64_t> infoField(const std::string& info, const std::string& key) {
   auto pos = info.find(key + ": ");
   if (pos == std::string::npos) return std::nullopt;
   return std::stoull(info.substr(pos + key.size() + 2));
}
//---------------------------------------------------------------------------
double ms(Clock::duration d) { return std::chrono::duration<double, std::milli>(d).count(); }
//---------------------------------------------------------------------------
double median(std::vector<double> v) {
   std::sort(v.begin(), v.end());
   return v.size() % 2 ? v[v.size() / 2] : (v[v.size() / 2 - 1] + v[v.size() / 2]) / 2;
}
//---------------------------------------------------------------------------
std::string csvField(const std::string& s) {
   std::string out = "\"";
   for (char c : s) out += (c == '"') ? std::string("\"\"") : std::string(1, c);
   return out + "\"";
}
//---------------------------------------------------------------------------
struct Row {
   std::string sampleId, method, configuration, status = "ok", error;
   size_t originalBytes = 0;
   uint64_t inputHash = 0;
   std::optional<uint64_t> tokenCount, tokenIdBytes, usedTokens;
   std::optional<size_t> payloadBytes, metadataBytes, footerBytes, bitmapBytes, totalStoredBytes, decodedBytes;
   std::optional<uint64_t> encodedHash, decodedHash;
   std::optional<bool> roundtripExact, encodedConsistent;
   std::vector<double> setupEncode, encode, setupDecode, decode;
};
//---------------------------------------------------------------------------
template <typename T>
std::string opt(const std::optional<T>& v) {
   if (!v) return "";
   if constexpr (std::is_same_v<T, bool>) return *v ? "true" : "false";
   else return std::to_string(*v);
}
//---------------------------------------------------------------------------
std::string optMedian(const std::vector<double>& v) {
   if (v.empty()) return "";
   char buffer[64];
   std::snprintf(buffer, sizeof(buffer), "%.6f", median(v));
   return buffer;
}
//---------------------------------------------------------------------------
void measureSgtt(const compressor::CompressorConfig& config, const std::vector<std::byte>& input, unsigned repetitions, Row& row, std::string& encodedHex, std::string& decodedHex) {
   std::vector<std::byte> padded(input.size() + inputPadding, std::byte{0});
   std::memcpy(padded.data(), input.data(), input.size());
   const std::span<std::byte> source(padded.data(), input.size());

   for (unsigned rep = 0; rep < repetitions; ++rep) {
      std::vector<std::byte> compressed(10 * input.size() + 64);

      auto t0 = Clock::now();
      auto encoder = compressor::Compressor::create(config);
      auto t1 = Clock::now();
      encoder->compress(source, compressed);
      auto t2 = Clock::now();
      const auto info = encoder->getInfo();

      auto t3 = Clock::now();
      auto decoderCompressor = compressor::Compressor::create(config, compressed);
      std::vector<std::byte> decoded(2 * decoderCompressor->getUncompressedSize(compressed));
      std::vector<std::vector<std::byte>> temporaryBuffers;
      auto t4 = Clock::now();
      decoderCompressor->decompress(compressed, decoded, temporaryBuffers);
      auto t5 = Clock::now();

      row.setupEncode.push_back(ms(t1 - t0));
      row.encode.push_back(ms(t2 - t1));
      row.setupDecode.push_back(ms(t4 - t3));
      row.decode.push_back(ms(t5 - t4));

      const uint64_t encodedHash = fnv1a64(compressed.data(), compressed.size());
      if (rep == 0) {
         row.tokenCount = infoField(info, "tokens");
         auto idBits = infoField(info, "token_id_size");
         if (idBits) row.tokenIdBytes = *idBits / 8;
         row.usedTokens = infoField(info, "used_tokens");
         row.totalStoredBytes = compressed.size();
         row.encodedHash = encodedHash;
         row.encodedConsistent = true;
         if (row.tokenCount && row.tokenIdBytes) {
            row.payloadBytes = *row.tokenCount * *row.tokenIdBytes;
            row.metadataBytes = compressed.size() - *row.payloadBytes;
            row.footerBytes = sgttFooterBytes;
            row.bitmapBytes = *row.metadataBytes - sgttFooterBytes;
         }
         row.decodedBytes = decoded.size();
         row.decodedHash = fnv1a64(decoded.data(), decoded.size());
         row.roundtripExact = decoded.size() == input.size() && std::memcmp(decoded.data(), input.data(), input.size()) == 0;
         encodedHex = hex(compressed.data(), compressed.size());
         decodedHex = hex(decoded.data(), decoded.size());
      } else if (encodedHash != *row.encodedHash || compressed.size() != *row.totalStoredBytes) {
         row.encodedConsistent = false;
      }
   }
}
//---------------------------------------------------------------------------
}
//---------------------------------------------------------------------------
int main(int argc, char** argv) {
   if (argc != 5) {
      std::cerr << "usage: phase1_harness <input.tsv> <measurements.csv> <artifacts.tsv> <repetitions>\n";
      return 2;
   }
   const unsigned repetitions = std::max(1ul, std::stoul(argv[4]));
   std::ifstream in(argv[1]);
   std::ofstream csv(argv[2]), artifacts(argv[3]);
   if (!in || !csv || !artifacts) {
      std::cerr << "cannot open input or output files\n";
      return 2;
   }
   csv << "sample_id,method,original_bytes,input_fnv1a64,token_count,token_id_bytes,used_tokens,payload_bytes,metadata_bytes,footer_bytes,bitmap_bytes,"
          "total_stored_bytes,encoded_fnv1a64,encoded_consistent_across_reps,decoded_bytes,decoded_fnv1a64,roundtrip_exact,"
          "setup_encode_ms_median,encode_ms_median,setup_decode_ms_median,decode_ms_median,timed_repetitions,status,error_message,configuration\n";
   artifacts << "sample_id\tmethod\tencoded_hex\tdecoded_hex\n";

   const auto allMethods = methods();
   std::string line;
   size_t failures = 0;
   while (std::getline(in, line)) {
      auto tab = line.find('\t');
      if (tab == std::string::npos) continue;
      const std::string sampleId = line.substr(0, tab);
      const auto input = unhex(line.substr(tab + 1));

      for (const auto& method : allMethods) {
         Row row;
         row.sampleId = sampleId;
         row.method = method.name;
         row.configuration = method.configuration;
         row.originalBytes = input.size();
         row.inputHash = fnv1a64(input.data(), input.size());
         std::string encodedHex, decodedHex;

         if (!method.config) {
            row.payloadBytes = input.size();
            row.metadataBytes = 0;
            row.totalStoredBytes = input.size();
            row.decodedBytes = input.size();
            row.decodedHash = row.inputHash;
            row.roundtripExact = true;
            row.status = "ok";
         } else if (input.empty()) {
            // Tokenizer::compress/decompress assert uncompressedSize > 0 (Tokenizer.cpp:154-155, 235-236); see Phase 0 Finding 1.
            row.status = "unsupported_input";
            row.error = "empty input is outside the upstream sgtt contract (asserted uncompressedSize > 0); not executed";
         } else {
            try {
               measureSgtt(*method.config, input, repetitions, row, encodedHex, decodedHex);
               if (!row.roundtripExact.value_or(false)) row.status = "roundtrip_mismatch";
               else if (!row.encodedConsistent.value_or(false)) row.status = "nondeterministic_encoding";
            } catch (const std::exception& e) {
               row.status = "error";
               row.error = e.what();
            }
         }
         if (row.status != "ok" && row.status != "unsupported_input") ++failures;

         csv << row.sampleId << ',' << row.method << ',' << row.originalBytes << ',' << row.inputHash << ',' << opt(row.tokenCount) << ',' << opt(row.tokenIdBytes) << ','
             << opt(row.usedTokens) << ',' << opt(row.payloadBytes) << ',' << opt(row.metadataBytes) << ',' << opt(row.footerBytes) << ',' << opt(row.bitmapBytes) << ','
             << opt(row.totalStoredBytes) << ',' << opt(row.encodedHash) << ',' << opt(row.encodedConsistent) << ',' << opt(row.decodedBytes) << ',' << opt(row.decodedHash) << ','
             << opt(row.roundtripExact) << ',' << optMedian(row.setupEncode) << ',' << optMedian(row.encode) << ',' << optMedian(row.setupDecode) << ',' << optMedian(row.decode) << ','
             << row.encode.size() << ',' << row.status << ',' << csvField(row.error) << ',' << csvField(row.configuration) << '\n';
         if (method.config && !encodedHex.empty()) artifacts << row.sampleId << '\t' << row.method << '\t' << encodedHex << '\t' << decodedHex << '\n';
      }
   }
   std::cerr << "failures (excluding unsupported inputs): " << failures << "\n";
   return failures == 0 ? 0 : 1;
}
