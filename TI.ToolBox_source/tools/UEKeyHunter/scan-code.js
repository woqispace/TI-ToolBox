'use strict';
// scan-code.js -- find AES keys that are embedded in *code* (mov dword [mem], imm32 chains).
//
// This is the mode that catches keys a plain 32-byte scan misses. Candidates are extracted
// from decoded C7 instructions by lib/codekeys.js, then:
//   1) cheap prefilter: AES-decrypt the first 16 bytes of the pak index, expect the FString
//      length + "../../.." mount point (one AES block per candidate)
//   2) hard proof: full index decrypt -> SHA1 must equal the value stored in the pak
//
// Usage:
//   node scan-code.js <game.exe> [--pak=<x.pak>] [--report=AESKEY.txt] [--maxgap=8] [--limit=N]
//   node scan-code.js <game.exe> --entropy        (no pak: rank candidates by entropy, AESDumpster style)

const fs = require('fs');
const path = require('path');
const cfg = require('./config');
const { readPakInfo } = require('./lib/pak');
const { verifyIndex, isMountPoint } = require('./lib/oracle');
const { expandKey, decryptBlock } = require('./lib/aes256');
const { extractCandidates } = require('./lib/codekeys');

function argStr(name, def) {
  const hit = process.argv.find((a) => a.startsWith('--' + name + '='));
  if (!hit) return def;
  return hit.slice(name.length + 3).replace(/^"|"$/g, '');
}
function argNum(name, def) {
  const v = argStr(name, null);
  if (v === null) return def;
  const n = Number(v);
  return Number.isFinite(n) ? n : def;
}

function hexEntropy(hex) {
  const freq = new Map();
  for (const ch of hex) freq.set(ch, (freq.get(ch) || 0) + 1);
  let h = 0;
  for (const c of freq.values()) {
    const p = c / hex.length;
    h -= p * Math.log2(p);
  }
  return h;
}

const target = process.argv.slice(2).find((a) => !a.startsWith('--')) || cfg.EXE;
if (!target || !fs.existsSync(target)) {
  console.error('找不到要扫描的 exe：' + target);
  process.exit(1);
}

const entropyMode = process.argv.includes('--entropy');
let pakPath = null;
if (!entropyMode) {
  pakPath = argStr('pak', null) || cfg.PAK || null;
  if (!pakPath) {
    try {
      pakPath = cfg.needPak();
    } catch (e) {
      console.error('没有指定 pak（--pak=... 或在 config.js / target.json 里配好），可加 --entropy 只出候选。');
      process.exit(1);
    }
  }
}

let pakInfo = null;
let firstBlock = null;
if (pakPath) {
  pakInfo = readPakInfo(pakPath);
  const fd = fs.openSync(pakPath, 'r');
  firstBlock = Buffer.alloc(16);
  fs.readSync(fd, firstBlock, 0, 16, pakInfo.indexOffset);
  fs.closeSync(fd);
}

console.log('目标   : ' + target + '  (' + fs.statSync(target).size + ' 字节)');
console.log('模式   : ' + (entropyMode ? '仅候选（entropy 排序）' : '代码内 key → pak 复核'));
if (pakPath) {
  console.log('pak    : ' + pakPath);
  console.log('索引   : @' + pakInfo.indexOffset + ' size=' + pakInfo.indexSize + ' sha1=' + pakInfo.indexHash);
}
console.log('');

const buf = fs.readFileSync(target);
const t0 = Date.now();
const maxGap = argNum('maxgap', 8);
const limit = argNum('limit', 0);
const report = argStr('report', path.join(path.dirname(require.main.filename), 'AESKEY.txt'));

console.log('正在解码 C7 指令链…');
const cands = extractCandidates(buf, { maxGap, limit });
console.log('候选 key: ' + cands.length + ' 个（用时 ' + ((Date.now() - t0) / 1000).toFixed(1) + 's）');
if (!cands.length) {
  console.log('没有找到 8 条连续的 mov dword imm32 指令链 —— 这个 exe 可能不是 UE，或 key 不在代码里。');
  process.exit(0);
}

let hits = 0;
if (entropyMode) {
  const ranked = cands
    .map((c) => ({ keyHex: c.keyHex, ent: hexEntropy(c.keyHex), off: c.instrStarts[0] }))
    .filter((c) => c.ent >= 3.3)
    .sort((a, b) => b.ent - a.ent)
    .slice(0, 40);
  console.log('── entropy ≥ 3.3 的候选（高熵在前，需自行验证）──');
  for (const r of ranked) {
    console.log('  0x' + r.keyHex + '  entropy=' + r.ent.toFixed(4) + '  @0x' + r.off.toString(16));
  }
  if (!ranked.length) console.log('  （没有熵 ≥ 3.3 的候选）');
  process.exit(0);
}

const rk = Buffer.alloc(240);
const out = Buffer.alloc(16);
for (const c of cands) {
  const key = Buffer.from(c.keyHex, 'hex');
  expandKey(key, rk);
  decryptBlock(rk, firstBlock, out);
  if (!isMountPoint(out)) continue;

  const v = verifyIndex(c.keyHex, pakPath, pakInfo);
  if (!v.match) continue;

  hits += 1;
  console.log('');
  console.log('[HIT] 指令偏移 @0x' + c.instrStarts[0].toString(16) + '  imm 偏移 ' + c.immOffs.map((x) => '0x' + x.toString(16)).join(', '));
  console.log('      key = 0x' + c.keyHex);
  console.log('      整索引 SHA1 = ' + v.sha);
  console.log('      存储 SHA1   = ' + v.stored + '  ===> 确定正确');
  try {
    fs.appendFileSync(report, c.keyHex + '\tIndexSHA1(scan-code)\t' + target + '\n');
  } catch (e) {
    console.log('      （写 AESKEY.txt 失败：' + e.message + '）');
  }
}

const dt = ((Date.now() - t0) / 1000).toFixed(1);
console.log('');
if (hits) {
  console.log('完成：命中 ' + hits + ' 个，用时 ' + dt + 's，已追加到 ' + report);
} else {
  console.log('完成：命中 0 个，用时 ' + dt + 's —— 这个 exe 的代码里没有能解开的 key。');
  console.log('提示：key 可能只在运行期内存里（用 dump-mem.ps1 + scan-mem.js），或者被 XOR mask 表二次混淆。');
}
