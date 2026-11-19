import type {
  CompiledBlockArtifact,
  MerkleBlockDiffEntry,
  MerkleSyncManifest,
} from '../ir/afHyperGraph.types';

/** FIPS 180-4 SHA-256 initial hash values (fractional parts of sqrt of first 8 primes). */
const SHA256_INIT = new Int32Array([
  0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
  0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
]);

/** FIPS 180-4 SHA-256 round constants (fractional parts of cube roots of first 64 primes). */
const SHA256_K = new Int32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

const DECORATIVE_TIMESTAMP_REGEX =
  /(?:timestamp|generated\s+(?:at|on)|updated\s*at|build\s*time|export\s*time|生成时间|导出时间|时间戳|\d{4}[-/]\d{2}[-/]\d{2}[T\s_]+\d{2}:\d{2})/i;

const TRACKED_INTERFACE_START_REGEX = /^(?:VAR_INPUT|VAR_OUTPUT|VAR_IN_OUT|VAR_STAT|VAR)\b/i;
const ANY_VAR_START_REGEX = /^VAR(?:_[A-Z0-9]+)?\b/i;
const VAR_END_REGEX = /^END_VAR\b/i;
const BEGIN_REGEX = /^BEGIN\b/i;

const DEFAULT_TIA_TARGET = 'TIA Portal V17 Openness STA Daemon';
const INSTANCE_DB_CASCADE_REASON = '接口时间戳刷新：需连带重建背景 DB';

function encodeUtf8Manual(input: string): Uint8Array {
  const out: number[] = [];
  for (let i = 0; i < input.length; i++) {
    const code = input.charCodeAt(i);
    if (code < 0x80) {
      out.push(code);
    } else if (code < 0x800) {
      out.push(0xc0 | (code >> 6), 0x80 | (code & 0x3f));
    } else if (code >= 0xd800 && code <= 0xdbff) {
      const next = i + 1 < input.length ? input.charCodeAt(i + 1) : 0;
      if (next >= 0xdc00 && next <= 0xdfff) {
        const cp = 0x10000 + (((code - 0xd800) << 10) | (next - 0xdc00));
        out.push(
          0xf0 | (cp >> 18),
          0x80 | ((cp >> 12) & 0x3f),
          0x80 | ((cp >> 6) & 0x3f),
          0x80 | (cp & 0x3f)
        );
        i++;
      } else {
        out.push(0xef, 0xbf, 0xbd);
      }
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      out.push(0xef, 0xbf, 0xbd);
    } else {
      out.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f));
    }
  }
  return new Uint8Array(out);
}

function encodeUtf8(input: string): Uint8Array {
  if (typeof TextEncoder !== 'undefined') {
    return new TextEncoder().encode(input);
  }
  return encodeUtf8Manual(input);
}

function rotr(value: number, bits: number): number {
  return (value >>> bits) | (value << (32 - bits));
}

/**
 * Pure TypeScript synchronous FIPS 180-4 SHA-256 implementation.
 * Safe in both browser (Vite) and Node (Vitest) without node:crypto or async crypto.subtle.
 */
export function sha256Hex(input: string): string {
  const bytes = encodeUtf8(input);
  const byteLen = bytes.length;
  const paddedLen = Math.ceil((byteLen + 9) / 64) * 64;
  const padded = new Uint8Array(paddedLen);
  padded.set(bytes, 0);
  padded[byteLen] = 0x80;

  const bitLen = byteLen * 8;
  const highBits = Math.floor(bitLen / 0x100000000);
  const lowBits = bitLen >>> 0;

  padded[paddedLen - 8] = (highBits >>> 24) & 0xff;
  padded[paddedLen - 7] = (highBits >>> 16) & 0xff;
  padded[paddedLen - 6] = (highBits >>> 8) & 0xff;
  padded[paddedLen - 5] = highBits & 0xff;
  padded[paddedLen - 4] = (lowBits >>> 24) & 0xff;
  padded[paddedLen - 3] = (lowBits >>> 16) & 0xff;
  padded[paddedLen - 2] = (lowBits >>> 8) & 0xff;
  padded[paddedLen - 1] = lowBits & 0xff;

  let h0 = SHA256_INIT[0];
  let h1 = SHA256_INIT[1];
  let h2 = SHA256_INIT[2];
  let h3 = SHA256_INIT[3];
  let h4 = SHA256_INIT[4];
  let h5 = SHA256_INIT[5];
  let h6 = SHA256_INIT[6];
  let h7 = SHA256_INIT[7];

  const w = new Int32Array(64);

  for (let offset = 0; offset < paddedLen; offset += 64) {
    for (let i = 0; i < 16; i++) {
      const idx = offset + i * 4;
      w[i] =
        ((padded[idx] << 24) |
          (padded[idx + 1] << 16) |
          (padded[idx + 2] << 8) |
          padded[idx + 3]) |
        0;
    }

    for (let i = 16; i < 64; i++) {
      const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
    }

    let a = h0;
    let b = h1;
    let c = h2;
    let d = h3;
    let e = h4;
    let f = h5;
    let g = h6;
    let h = h7;

    for (let i = 0; i < 64; i++) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const temp1 = (h + S1 + ch + SHA256_K[i] + w[i]) | 0;
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (S0 + maj) | 0;

      h = g;
      g = f;
      f = e;
      e = (d + temp1) | 0;
      d = c;
      c = b;
      b = a;
      a = (temp1 + temp2) | 0;
    }

    h0 = (h0 + a) | 0;
    h1 = (h1 + b) | 0;
    h2 = (h2 + c) | 0;
    h3 = (h3 + d) | 0;
    h4 = (h4 + e) | 0;
    h5 = (h5 + f) | 0;
    h6 = (h6 + g) | 0;
    h7 = (h7 + h) | 0;
  }

  return [h0, h1, h2, h3, h4, h5, h6, h7]
    .map((word) => (word >>> 0).toString(16).padStart(8, '0'))
    .join('');
}

function isDecorativeCommentLine(trimmedEnd: string): boolean {
  const trimmed = trimmedEnd.trimStart();
  if (trimmed.startsWith('//')) {
    const body = trimmed.slice(2).trim();
    return body.length === 0 || DECORATIVE_TIMESTAMP_REGEX.test(trimmed);
  }
  if (trimmed.startsWith('(*') && trimmed.endsWith('*)')) {
    const body = trimmed.slice(2, -2).trim();
    return body.length === 0 || DECORATIVE_TIMESTAMP_REGEX.test(trimmed);
  }
  return false;
}

/**
 * Normalize SCL AST text for deterministic hashing:
 * - Unify CRLF / CR -> LF
 * - Strip trailing whitespace per line
 * - Drop decorative empty or timestamp-only comment lines (`//` or `(* ... *)`)
 * - Collapse consecutive blank lines and trim leading/trailing blank lines
 */
export function normalizeSclAst(scl: string): string {
  if (!scl) return '';

  const unified = scl.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  const rawLines = unified.split('\n');
  const normalized: string[] = [];
  let previousBlank = true;

  for (const rawLine of rawLines) {
    const trimmedEnd = rawLine.replace(/\s+$/, '');
    if (isDecorativeCommentLine(trimmedEnd)) {
      continue;
    }

    if (trimmedEnd.length === 0) {
      if (!previousBlank) {
        normalized.push('');
        previousBlank = true;
      }
      continue;
    }

    normalized.push(trimmedEnd);
    previousBlank = false;
  }

  while (normalized.length > 0 && normalized[normalized.length - 1].length === 0) {
    normalized.pop();
  }

  return normalized.join('\n');
}

/**
 * Extract canonicalized `VAR_INPUT` / `VAR_OUTPUT` / `VAR_IN_OUT` / `VAR_STAT` / `VAR`
 * declaration sections up to `END_VAR` so interface changes can be tracked separately
 * from implementation body changes.
 */
export function extractInterfaceSignature(scl: string): string {
  const normalized = normalizeSclAst(scl);
  if (!normalized) return '';

  const lines = normalized.split('\n');
  const collected: string[] = [];
  let inTrackedSection = false;
  let inUntrackedSection = false;

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;

    if (!inTrackedSection && !inUntrackedSection) {
      if (BEGIN_REGEX.test(trimmed)) {
        break;
      }
      if (TRACKED_INTERFACE_START_REGEX.test(trimmed)) {
        inTrackedSection = true;
        collected.push(trimmed);
      } else if (ANY_VAR_START_REGEX.test(trimmed)) {
        inUntrackedSection = true;
      }
      continue;
    }

    if (inUntrackedSection) {
      if (VAR_END_REGEX.test(trimmed)) {
        inUntrackedSection = false;
      }
      continue;
    }

    collected.push(trimmed);
    if (VAR_END_REGEX.test(trimmed)) {
      inTrackedSection = false;
    }
  }

  return collected.join('\n');
}

/**
 * Compute deterministic block hashes from SCL source:
 * - `fullSha256`: 64-char lowercase hex SHA-256 of normalized AST
 * - `merkleHash`: 8-char lowercase hex prefix (e.g. `"a94f82c1"`)
 * - `interfaceHash`: 16-char lowercase hex SHA-256 prefix of `extractInterfaceSignature`
 */
export function computeBlockHashes(sclCode: string): {
  merkleHash: string;
  fullSha256: string;
  interfaceHash: string;
} {
  const normalized = normalizeSclAst(sclCode);
  const fullSha256 = sha256Hex(normalized);
  const merkleHash = fullSha256.slice(0, 8);
  const interfaceSignature = extractInterfaceSignature(normalized);
  const interfaceHash = sha256Hex(interfaceSignature).slice(0, 16);
  return { merkleHash, fullSha256, interfaceHash };
}

type PreviousHashRecord = string | { merkleHash: string; interfaceHash?: string };

function lookupPreviousHash(
  stationId: string,
  blockName: string,
  previousHashes: Record<string, PreviousHashRecord>
): { merkleHash?: string; interfaceHash?: string } | null {
  const scopedKey = `${stationId}::${blockName}`;
  const raw = previousHashes[scopedKey] ?? previousHashes[blockName];

  let resolved = raw;
  if (resolved === undefined) {
    const scopedLower = scopedKey.toLowerCase();
    const blockLower = blockName.toLowerCase();
    for (const [key, value] of Object.entries(previousHashes)) {
      const lower = key.toLowerCase();
      if (lower === scopedLower || lower === blockLower) {
        resolved = value;
        break;
      }
    }
  }

  if (resolved === undefined || resolved === null) return null;

  if (typeof resolved === 'string') {
    const merkle = resolved.trim().toLowerCase();
    return merkle ? { merkleHash: merkle } : null;
  }

  const merkle = resolved.merkleHash?.trim().toLowerCase();
  const iface = resolved.interfaceHash?.trim().toLowerCase();
  if (!merkle && !iface) return null;
  return {
    ...(merkle ? { merkleHash: merkle } : {}),
    ...(iface ? { interfaceHash: iface } : {}),
  };
}

/**
 * Compute block-level incremental Merkle sync manifest for Openness STA daemon.
 * Aligns with `OpennessGuardrails`: whenever an `FB` block's `interfaceHash` changes
 * (or on initial sync), its associated `DB_<stationId>_Instances` / `instanceDbName` block
 * is automatically flagged `DIRTY` so TIA Portal refreshes the IDB timestamp.
 */
export function computeMerkleSyncManifest(
  stationId: string,
  artifacts: CompiledBlockArtifact[],
  previousHashes: Record<string, PreviousHashRecord>,
  tiaTarget = DEFAULT_TIA_TARGET
): MerkleSyncManifest {
  const entries: MerkleBlockDiffEntry[] = [];
  const fbInterfaceChanged = new Map<string, boolean>();

  for (const artifact of artifacts) {
    const computed = computeBlockHashes(artifact.sclCode);
    const merkleHash = artifact.merkleHash || computed.merkleHash;
    const interfaceHash = artifact.interfaceHash || computed.interfaceHash;
    const prev = lookupPreviousHash(stationId, artifact.blockName, previousHashes);

    const hashChanged = !prev || !prev.merkleHash || prev.merkleHash !== merkleHash;
    const ifaceChanged =
      !prev ||
      (prev.interfaceHash !== undefined && prev.interfaceHash !== interfaceHash);

    if (artifact.blockType === 'FB') {
      fbInterfaceChanged.set(artifact.blockName, ifaceChanged);
    }

    let reason: string;
    if (!prev || !prev.merkleHash) {
      reason = '首次同步（无历史哈希记录）';
    } else if (hashChanged) {
      reason = ifaceChanged
        ? '块接口与逻辑哈希均变更 -> 单块增量热替换'
        : '块逻辑 Merkle Hash 变更 -> 单块增量热替换';
    } else {
      reason = '哈希未变更 -> 跳过导入与编译';
    }

    entries.push({
      blockName: artifact.blockName,
      blockType: artifact.blockType,
      merkleHash,
      ...(prev?.merkleHash ? { previousHash: prev.merkleHash } : {}),
      status: hashChanged ? 'DIRTY' : 'UNCHANGED',
      reason,
      sclCode: artifact.sclCode,
      interfaceHash,
    });
  }

  // Cascade FB interface timestamp refresh onto associated Instance DBs
  const entryByName = new Map(entries.map((entry) => [entry.blockName, entry]));
  const stationInstancesDbName = `DB_${stationId}_Instances`;

  for (const artifact of artifacts) {
    if (artifact.blockType !== 'FB') continue;
    if (!fbInterfaceChanged.get(artifact.blockName)) continue;

    const candidateDbNames: string[] = [];
    if (artifact.instanceDbName && entryByName.has(artifact.instanceDbName)) {
      candidateDbNames.push(artifact.instanceDbName);
    } else if (entryByName.has(stationInstancesDbName)) {
      candidateDbNames.push(stationInstancesDbName);
    }

    for (const dbName of candidateDbNames) {
      const dbEntry = entryByName.get(dbName);
      if (!dbEntry || dbEntry.blockType !== 'DB') continue;

      dbEntry.status = 'DIRTY';
      const cascadeNote = `${INSTANCE_DB_CASCADE_REASON} (${artifact.blockName})`;
      if (!dbEntry.reason) {
        dbEntry.reason = cascadeNote;
      } else if (!dbEntry.reason.includes(INSTANCE_DB_CASCADE_REASON)) {
        dbEntry.reason = `${dbEntry.reason}; ${cascadeNote}`;
      }
    }
  }

  const dirtyCount = entries.filter((entry) => entry.status === 'DIRTY').length;
  const unchangedCount = entries.length - dirtyCount;
  const estimatedSyncSeconds =
    dirtyCount === 0 ? 0 : Number((dirtyCount * 1.18).toFixed(2));

  return {
    stationId,
    tiaTarget: tiaTarget || DEFAULT_TIA_TARGET,
    dirtyCount,
    unchangedCount,
    estimatedSyncSeconds,
    entries,
  };
}
