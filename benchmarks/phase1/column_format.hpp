#pragma once
// Project-owned column container (format "HCC1") wrapping the unmodified upstream codec blob.
// Layout (all methods):
//   magic "HCC1" (4) | version u8 = 1 | codec u8 (0 raw, 1 sgtt, 2 P1/P2a, 3 P2b)      -> header_bytes = 6
//   varint value_count | value_count x varint byte_length | varint blob_length            -> boundary_metadata_bytes
//   blob: raw = concatenated value bytes; sgtt = upstream Compressor::compress output of the
//         concatenated value bytes (token IDs | dense bitmap | 24-byte footer). Absent when blob_length == 0.
// Varints are unsigned LEB128. The codec is not called when the concatenated payload is empty
// (upstream sgtt asserts non-empty input), so empty columns and all-empty columns have blob_length 0.
#include "compressor/Compressor.hpp"
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <optional>
#include <span>
#include <stdexcept>
#include <string>
#include <vector>
//---------------------------------------------------------------------------
namespace hashcode::column {
//---------------------------------------------------------------------------
inline constexpr char magic[4] = {'H', 'C', 'C', '1'};
inline constexpr uint8_t formatVersion = 1;
inline constexpr size_t headerBytes = 6;
inline constexpr size_t sgttFooterBytes = 24;
inline constexpr size_t upstreamInputPadding = 16;
enum class Codec : uint8_t { Raw = 0, Sgtt = 1, P1 = 2, P2b = 3 };
//---------------------------------------------------------------------------
inline void putVarint(std::vector<std::byte>& out, uint64_t v) {
   do {
      uint8_t b = v & 0x7F;
      v >>= 7;
      out.push_back(static_cast<std::byte>(b | (v ? 0x80 : 0)));
   } while (v);
}
//---------------------------------------------------------------------------
inline uint64_t getVarint(std::span<const std::byte> in, size_t& pos) {
   uint64_t v = 0;
   for (unsigned shift = 0; shift < 64; shift += 7) {
      if (pos >= in.size()) throw std::runtime_error("HCC1: truncated varint");
      auto b = static_cast<uint8_t>(in[pos++]);
      v |= static_cast<uint64_t>(b & 0x7F) << shift;
      if (!(b & 0x80)) return v;
   }
   throw std::runtime_error("HCC1: varint too long");
}
//---------------------------------------------------------------------------
/// Concatenated value bytes, followed by the zero padding upstream codecs may read.
struct Payload {
   std::vector<std::byte> buffer;
   size_t size = 0;
   std::span<std::byte> bytes() { return {buffer.data(), size}; }
};
//---------------------------------------------------------------------------
inline Payload concatenate(const std::vector<std::string>& values) {
   Payload p;
   for (const auto& v : values) p.size += v.size();
   p.buffer.assign(p.size + upstreamInputPadding, std::byte{0});
   size_t pos = 0;
   for (const auto& v : values) {
      std::memcpy(p.buffer.data() + pos, v.data(), v.size());
      pos += v.size();
   }
   return p;
}
//---------------------------------------------------------------------------
struct Layout {
   size_t header = 0, boundary = 0, blob = 0;
};
//---------------------------------------------------------------------------
inline std::vector<std::byte> serialize(Codec codec, const std::vector<std::string>& values, std::span<const std::byte> blob, Layout& layout) {
   std::vector<std::byte> out;
   for (char c : magic) out.push_back(static_cast<std::byte>(c));
   out.push_back(static_cast<std::byte>(formatVersion));
   out.push_back(static_cast<std::byte>(codec));
   layout.header = out.size();
   putVarint(out, values.size());
   for (const auto& v : values) putVarint(out, v.size());
   putVarint(out, blob.size());
   layout.boundary = out.size() - layout.header;
   out.insert(out.end(), blob.begin(), blob.end());
   layout.blob = blob.size();
   return out;
}
//---------------------------------------------------------------------------
struct Parsed {
   Codec codec;
   std::vector<uint64_t> lengths;
   std::span<const std::byte> blob;
   Layout layout;
};
//---------------------------------------------------------------------------
inline Parsed parse(std::span<const std::byte> in) {
   if (in.size() < headerBytes || std::memcmp(in.data(), magic, 4) != 0) throw std::runtime_error("HCC1: bad magic");
   if (static_cast<uint8_t>(in[4]) != formatVersion) throw std::runtime_error("HCC1: unsupported version");
   auto codecByte = static_cast<uint8_t>(in[5]);
   if (codecByte > 3) throw std::runtime_error("HCC1: unknown codec");
   Parsed p{static_cast<Codec>(codecByte), {}, {}, {}};
   p.layout.header = headerBytes;
   size_t pos = headerBytes;
   const uint64_t count = getVarint(in, pos);
   if (count > in.size()) throw std::runtime_error("HCC1: implausible value count");
   p.lengths.reserve(count);
   for (uint64_t i = 0; i < count; ++i) p.lengths.push_back(getVarint(in, pos));
   const uint64_t blobLength = getVarint(in, pos);
   p.layout.boundary = pos - headerBytes;
   if (blobLength != in.size() - pos) throw std::runtime_error("HCC1: blob length mismatch");
   p.blob = in.subspan(pos);
   p.layout.blob = blobLength;
   return p;
}
//---------------------------------------------------------------------------
inline std::vector<std::string> split(std::span<const std::byte> decoded, const std::vector<uint64_t>& lengths) {
   uint64_t total = 0;
   for (auto l : lengths) total += l;
   if (total != decoded.size()) throw std::runtime_error("HCC1: decoded payload size does not match length table");
   std::vector<std::string> values;
   values.reserve(lengths.size());
   size_t pos = 0;
   for (auto l : lengths) {
      values.emplace_back(reinterpret_cast<const char*>(decoded.data()) + pos, l);
      pos += l;
   }
   return values;
}
//---------------------------------------------------------------------------
/// Upstream codec blob for the concatenated payload; empty when the payload is empty (codec not called).
inline std::vector<std::byte> encodeBlob(Codec codec, const std::optional<sgtt::compressor::CompressorConfig>& config, Payload& payload) {
   if (payload.size == 0) return {};
   if (codec == Codec::Raw) return {payload.buffer.begin(), payload.buffer.begin() + payload.size};
   std::vector<std::byte> blob(10 * payload.size + 64);
   sgtt::compressor::Compressor::create(*config)->compress(payload.bytes(), blob);
   return blob;
}
//---------------------------------------------------------------------------
inline std::vector<std::byte> decodeBlob(Codec codec, const std::optional<sgtt::compressor::CompressorConfig>& config, std::span<const std::byte> blob) {
   if (blob.empty()) return {};
   if (codec == Codec::Raw) return {blob.begin(), blob.end()};
   std::vector<std::byte> owned(blob.begin(), blob.end());
   auto decoder = sgtt::compressor::Compressor::create(*config, owned);
   std::vector<std::byte> decoded(2 * decoder->getUncompressedSize(owned));
   std::vector<std::vector<std::byte>> temporaryBuffers;
   decoder->decompress(owned, decoded, temporaryBuffers);
   return decoded;
}
//---------------------------------------------------------------------------
inline std::vector<std::byte> encodeColumn(Codec codec, const std::optional<sgtt::compressor::CompressorConfig>& config, const std::vector<std::string>& values, Layout& layout) {
   auto payload = concatenate(values);
   auto blob = encodeBlob(codec, config, payload);
   return serialize(codec, values, blob, layout);
}
//---------------------------------------------------------------------------
inline std::vector<std::string> decodeColumn(const std::optional<sgtt::compressor::CompressorConfig>& config, std::span<const std::byte> column) {
   auto parsed = parse(column);
   auto decoded = decodeBlob(parsed.codec, config, parsed.blob);
   return split(decoded, parsed.lengths);
}
//---------------------------------------------------------------------------
}
//---------------------------------------------------------------------------
