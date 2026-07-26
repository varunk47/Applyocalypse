/* 64-bit SimHash over 3-token shingles for near-duplicate job-description
 * detection (agency reposts and cross-listings that URL/company dedupe misses).
 * Adapted from santifer/career-ops fingerprint-core.mjs
 * (MIT License, Copyright (c) 2026 Santiago Fernandez de Valderrama). */

const FNV_OFFSET = 0xcbf29ce484222325n;
const FNV_PRIME = 0x100000001b3n;
const MASK64 = 0xffffffffffffffffn;

const fnv1a64 = (value: string): bigint => {
  let hash = FNV_OFFSET;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= BigInt(value.charCodeAt(index));
    hash = (hash * FNV_PRIME) & MASK64;
  }
  return hash;
};

const tokenize = (text: string): string[] =>
  text
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter((token) => token.length > 1);

/** 64-bit SimHash of the text as a 16-char hex string; null when too short to fingerprint. */
export const simhash64 = (text: string): string | null => {
  const tokens = tokenize(text);
  if (tokens.length < 12) {
    return null;
  }
  const weights = new Array<number>(64).fill(0);
  for (let index = 0; index + 2 < tokens.length; index += 1) {
    const shingleHash = fnv1a64(`${tokens[index]} ${tokens[index + 1]} ${tokens[index + 2]}`);
    for (let bit = 0; bit < 64; bit += 1) {
      weights[bit] = (weights[bit] ?? 0) + ((shingleHash >> BigInt(bit)) & 1n ? 1 : -1);
    }
  }
  let hash = 0n;
  for (let bit = 0; bit < 64; bit += 1) {
    if ((weights[bit] ?? 0) > 0) {
      hash |= 1n << BigInt(bit);
    }
  }
  return hash.toString(16).padStart(16, "0");
};

/** Similarity in [0, 1]: 1 - hammingDistance / 64. */
export const simhashSimilarity = (hexA: string, hexB: string): number => {
  let diff = BigInt(`0x${hexA}`) ^ BigInt(`0x${hexB}`);
  let distance = 0;
  while (diff !== 0n) {
    distance += Number(diff & 1n);
    diff >>= 1n;
  }
  return 1 - distance / 64;
};

/** Field-tested threshold from career-ops: >=0.92 (<=5 differing bits) marks a cross-listing. */
export const CROSS_LISTING_SIMILARITY = 0.92;
