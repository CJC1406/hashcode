#pragma once
// P1 akshara token table codec (project-owned; independent of upstream sgtt).
// Vocabulary file "P1V1": u32 LE entry count, then per entry u8 length + bytes (codec/p1/build_vocabulary.py).
// IDs 0-255 are the single bytes 0x00-0xFF, so every byte sequence is encodable (lossless byte fallback).
// Encoder: greedy longest-prefix match (16 down to 2 bytes), else the single-byte ID. Reads only [data, data + size).
// Blob: token IDs as u16 little-endian, then a 13-byte footer: "BTT1" | version u8 = 1 | table ID (first 8 bytes of the
// vocabulary file's SHA-256). Value boundaries live in the surrounding HCC1 container, not in the blob.
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iterator>
#include <span>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>
//---------------------------------------------------------------------------
namespace hashcode::p1 {
//---------------------------------------------------------------------------
inline constexpr size_t maxTokenBytes = 16;
inline constexpr size_t footerBytes = 13;
inline constexpr uint8_t blobVersion = 1;
//---------------------------------------------------------------------------
namespace detail {
/// Minimal SHA-256 (FIPS 180-4), used only to derive the vocabulary table ID.
inline std::array<uint8_t, 32> sha256(const std::vector<uint8_t>& msg) {
   static constexpr uint32_t k[64] = {
      0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
      0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
      0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
      0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
      0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
      0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};
   uint32_t h[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
   std::vector<uint8_t> m = msg;
   const uint64_t bits = static_cast<uint64_t>(msg.size()) * 8;
   m.push_back(0x80);
   while (m.size() % 64 != 56) m.push_back(0);
   for (int i = 7; i >= 0; --i) m.push_back(static_cast<uint8_t>(bits >> (8 * i)));
   auto rotr = [](uint32_t x, int n) { return (x >> n) | (x << (32 - n)); };
   for (size_t off = 0; off < m.size(); off += 64) {
      uint32_t w[64];
      for (int i = 0; i < 16; ++i) w[i] = (uint32_t(m[off + 4 * i]) << 24) | (uint32_t(m[off + 4 * i + 1]) << 16) | (uint32_t(m[off + 4 * i + 2]) << 8) | m[off + 4 * i + 3];
      for (int i = 16; i < 64; ++i) {
         uint32_t s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
         uint32_t s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
         w[i] = w[i - 16] + s0 + w[i - 7] + s1;
      }
      uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
      for (int i = 0; i < 64; ++i) {
         uint32_t t1 = hh + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + k[i] + w[i];
         uint32_t t2 = (rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
         hh = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
      }
      h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
   }
   std::array<uint8_t, 32> out{};
   for (int i = 0; i < 8; ++i)
      for (int j = 0; j < 4; ++j) out[4 * i + j] = static_cast<uint8_t>(h[i] >> (24 - 8 * j));
   return out;
}
}
//---------------------------------------------------------------------------
class Vocabulary {
   std::vector<std::string> entries;
   std::unordered_map<std::string_view, uint16_t> lookup[maxTokenBytes + 1];
   std::array<uint8_t, 8> id{};
   size_t fileBytes = 0;

   public:
   explicit Vocabulary(const std::string& path) {
      std::ifstream in(path, std::ios::binary);
      if (!in) throw std::runtime_error("P1: cannot open vocabulary " + path);
      std::vector<uint8_t> raw((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
      fileBytes = raw.size();
      if (raw.size() < 8 || std::memcmp(raw.data(), "P1V1", 4) != 0) throw std::runtime_error("P1: bad vocabulary magic");
      const uint32_t count = raw[4] | (raw[5] << 8) | (raw[6] << 16) | (uint32_t(raw[7]) << 24);
      if (count < 256 || count > 65536) throw std::runtime_error("P1: vocabulary entry count out of range");
      size_t pos = 8;
      entries.reserve(count);
      for (uint32_t i = 0; i < count; ++i) {
         if (pos >= raw.size()) throw std::runtime_error("P1: truncated vocabulary");
         const size_t len = raw[pos++];
         if (len == 0 || len > maxTokenBytes || pos + len > raw.size()) throw std::runtime_error("P1: bad vocabulary entry");
         entries.emplace_back(reinterpret_cast<const char*>(raw.data() + pos), len);
         pos += len;
      }
      if (pos != raw.size()) throw std::runtime_error("P1: trailing bytes in vocabulary");
      for (uint32_t i = 0; i < 256; ++i)
         if (entries[i].size() != 1 || static_cast<uint8_t>(entries[i][0]) != i) throw std::runtime_error("P1: IDs 0-255 must be the single bytes");
      for (uint32_t i = 256; i < count; ++i) {
         const auto& e = entries[i];
         if (e.size() < 2) throw std::runtime_error("P1: multi-byte entries must have at least 2 bytes");
         if (!lookup[e.size()].emplace(std::string_view(e), static_cast<uint16_t>(i)).second) throw std::runtime_error("P1: duplicate vocabulary entry");
      }
      auto digest = detail::sha256(raw);
      std::memcpy(id.data(), digest.data(), 8);
   }
   size_t size() const { return entries.size(); }
   size_t serializedBytes() const { return fileBytes; }
   const std::array<uint8_t, 8>& tableId() const { return id; }
   const std::string& entry(uint16_t i) const { return entries[i]; }

   /// Token IDs for data; fallbackTokens counts single-byte IDs emitted because no longer entry matched.
   std::vector<uint16_t> tokenize(std::span<const std::byte> data, size_t& fallbackTokens) const {
      std::vector<uint16_t> ids;
      ids.reserve(data.size());
      fallbackTokens = 0;
      const char* p = reinterpret_cast<const char*>(data.data());
      size_t pos = 0;
      while (pos < data.size()) {
         const size_t limit = std::min(maxTokenBytes, data.size() - pos);
         bool matched = false;
         for (size_t len = limit; len >= 2; --len) {
            auto it = lookup[len].find(std::string_view(p + pos, len));
            if (it != lookup[len].end()) {
               ids.push_back(it->second);
               pos += len;
               matched = true;
               break;
            }
         }
         if (!matched) {
            ids.push_back(static_cast<uint8_t>(p[pos]));
            ++pos;
            ++fallbackTokens;
         }
      }
      return ids;
   }
};
//---------------------------------------------------------------------------
inline std::vector<std::byte> encodeBlob(const Vocabulary& v, std::span<const std::byte> data, size_t& tokenCount, size_t& fallbackTokens) {
   auto ids = v.tokenize(data, fallbackTokens);
   tokenCount = ids.size();
   std::vector<std::byte> blob;
   blob.reserve(2 * ids.size() + footerBytes);
   for (auto i : ids) {
      blob.push_back(static_cast<std::byte>(i & 0xFF));
      blob.push_back(static_cast<std::byte>(i >> 8));
   }
   for (char c : std::string_view("BTT1")) blob.push_back(static_cast<std::byte>(c));
   blob.push_back(static_cast<std::byte>(blobVersion));
   for (auto b : v.tableId()) blob.push_back(static_cast<std::byte>(b));
   return blob;
}
//---------------------------------------------------------------------------
inline std::vector<std::byte> decodeBlob(const Vocabulary& v, std::span<const std::byte> blob) {
   if (blob.size() < footerBytes) throw std::runtime_error("P1: blob shorter than footer");
   const auto* f = blob.data() + blob.size() - footerBytes;
   if (std::memcmp(f, "BTT1", 4) != 0) throw std::runtime_error("P1: bad footer magic");
   if (static_cast<uint8_t>(f[4]) != blobVersion) throw std::runtime_error("P1: unsupported blob version");
   if (std::memcmp(f + 5, v.tableId().data(), 8) != 0) throw std::runtime_error("P1: blob was encoded with a different vocabulary");
   const size_t idBytes = blob.size() - footerBytes;
   if (idBytes % 2) throw std::runtime_error("P1: odd token-ID byte count");
   std::vector<std::byte> out;
   for (size_t i = 0; i < idBytes; i += 2) {
      const uint16_t tokenId = static_cast<uint8_t>(blob[i]) | (static_cast<uint16_t>(static_cast<uint8_t>(blob[i + 1])) << 8);
      if (tokenId >= v.size()) throw std::runtime_error("P1: token ID outside vocabulary");
      const auto& e = v.entry(tokenId);
      for (char c : e) out.push_back(static_cast<std::byte>(c));
   }
   return out;
}
//---------------------------------------------------------------------------
}
//---------------------------------------------------------------------------
