'use strict';
// codekeys.js -- "code-embedded key" extractor.
//
// Why this exists: AESDumpster finds keys that a plain 32-byte scan can never see.
// UE initialises FAES::FAESKey with eight consecutive `mov dword ptr [mem], imm32`
// instructions (opcode C7), so the key's eight dwords live inside eight instructions
// scattered every 7-11 bytes. There is no contiguous 32-byte key anywhere in the file.
//
// This module decodes those C7 instructions, pulls out each imm32, and stitches the
// imm32s of 8 consecutive instructions into candidate keys. No heuristics: the caller
// validates candidates against the pak index SHA1, so false positives cannot survive.

// Decode one `C7` (mov r/m32, imm32) that starts at index i.
// Returns { immOff, end } or null when the bytes cannot be a valid instruction.
function decodeC7(buf, i, end) {
  let j = i + 1;
  if (j >= end) return null;
  const modrm = buf[j];
  j += 1;
  const mod = modrm >> 6;
  const rm = modrm & 7;

  if (mod !== 3 && rm === 4) {
    // SIB byte present
    if (j >= end) return null;
    const sib = buf[j];
    j += 1;
    if (mod === 0 && (sib & 7) === 5) j += 4; // disp32 follows
  }

  if (mod === 0) {
    if (rm === 5) j += 4; // RIP-relative disp32
  } else if (mod === 1) {
    j += 1; // disp8
  } else if (mod === 2) {
    j += 4; // disp32
  }

  if (j + 4 > end) return null;
  return { immOff: j, end: j + 4 };
}

// Walk the buffer and collect every decoded C7 immediate.
function collectImmediates(buf, end) {
  const out = [];
  for (let i = 0; i + 7 <= end; i++) {
    if (buf[i] !== 0xc7) continue;
    const d = decodeC7(buf, i, end);
    if (!d) continue;
    out.push({ start: i, immOff: d.immOff, end: d.end, imm: buf.readUInt32LE(d.immOff) });
    i = d.end - 1;
  }
  return out;
}

// Split the immediate stream into runs of neighbouring instructions.
// A run breaks when the gap to the next instruction is larger than maxGap bytes.
function splitRuns(imms, maxGap) {
  const runs = [];
  let cur = [];
  for (const it of imms) {
    if (cur.length && it.start - cur[cur.length - 1].end > maxGap) {
      runs.push(cur);
      cur = [];
    }
    cur.push(it);
  }
  if (cur.length) runs.push(cur);
  return runs;
}

function toHexKey(dwords) {
  const b = Buffer.alloc(32);
  for (let i = 0; i < 8; i++) b.writeUInt32LE(dwords[i] >>> 0, i * 4);
  return b.toString('hex').toUpperCase();
}

function looksBogus(dwords) {
  let zero = 0;
  let same = true;
  for (let i = 0; i < 8; i++) {
    if (dwords[i] === 0) zero += 1;
    if (i && dwords[i] !== dwords[0]) same = false;
  }
  return zero >= 4 || same;
}

// Extract candidate keys from a buffer.
// opts.maxGap  : max byte gap inside one run (default 8)
// opts.limit   : stop after this many candidates (0 = unlimited)
// opts.onCandidate(cand) : optional callback { keyHex, immOffs, instrStarts }
function extractCandidates(buf, opts) {
  const o = opts || {};
  const maxGap = o.maxGap === undefined ? 8 : o.maxGap;
  const limit = o.limit || 0;
  const end = buf.length;

  const imms = collectImmediates(buf, end);
  const runs = splitRuns(imms, maxGap);
  const seen = new Set();
  const out = [];

  for (const run of runs) {
    if (run.length < 8) continue;
    for (let s = 0; s + 8 <= run.length; s++) {
      const win = run.slice(s, s + 8);
      const dwords = win.map((x) => x.imm);
      if (looksBogus(dwords)) continue;
      const keyHex = toHexKey(dwords);
      if (seen.has(keyHex)) continue;
      seen.add(keyHex);
      const cand = {
        keyHex,
        immOffs: win.map((x) => x.immOff),
        instrStarts: win.map((x) => x.start),
      };
      out.push(cand);
      if (o.onCandidate) o.onCandidate(cand);
      if (limit && out.length >= limit) return out;
    }
  }
  return out;
}

module.exports = { extractCandidates, collectImmediates, splitRuns, decodeC7, toHexKey };
