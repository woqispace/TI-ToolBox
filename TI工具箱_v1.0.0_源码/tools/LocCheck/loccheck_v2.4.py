#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LocCheck v2.2 - UE locres 工具链（体检 / 导出 / 新增 / 回写 / 自检）

v1.0 只会"体检"：判断一个游戏能不能用 locres 汉化。
v2.0 补上真正干活的部分，重点是 **能给 locres 新增条目**
（UnrealLocres.exe 的 import 只更新已有 key，新 key 会被静默丢弃）：

    info    <locres>                     看版本/条数/编码/头部
    export  <locres> <csv>               导出 key,source,target
    import  <base.locres> <csv> <out>    回写（默认：更新已有 + 新增缺失）
    merge   <base.csv> <add.csv> -o <c>  两个 CSV 合并去重
    scan    <dir|file> [--out csv]       从 uexp/uasset 抽带 key 的 FText
    verify  <locres> [--csv csv]         条数/重复/空值/中文率自检
    check   --game <dir>                 v1.0 的体检（能不能用 locres）
    probe   --game <dir>                 v1.0 的 ZZZTEST 探针

只用标准库。导出格式与 UnrealLocres 的 `key,source,target` 兼容，两边可以互换。
"""
from __future__ import print_function

import argparse
import csv
import io
import os
import re
import struct
import sys
import time
import subprocess
import shutil

IS_WIN = (os.name == 'nt')
HEX32 = re.compile(r'^[0-9A-Fa-f]{32}$')

# 真实 locres 的固定头尾（取自 DeltaZone Game.locres，逐字节对齐）
DEFAULT_HEADER = struct.pack('<I', 2) + b'\x00' * 8            # version=2 + extra(4) + count 位(4) = 12 B
DEFAULT_TRAILER = bytes.fromhex('e01a14aff5ffffff') + 'Text Block'.encode('utf-16-le') + b'\x00\x00'
NS_KEY, NS_HASH, NS_TEXT = 'UMG', 1, 'TextBlockDefaultValue'     # 真实文件末尾都跟着这条命名空间记录

# ------------------------------------------------------------------ 基础


def u32(b, off):
    return struct.unpack_from('<I', b, off)[0]


def i32(b, off):
    return struct.unpack_from('<i', b, off)[0]


class Str(object):
    """FString，记住原始字节以便逐字节还原。"""

    __slots__ = ('text', 'raw', 'n')

    def __init__(self, text, raw, n):
        self.text = text
        self.raw = raw
        self.n = n

    @classmethod
    def read(cls, b, off):
        n = i32(b, off)
        start = off
        off += 4
        if n == 0:
            return cls('', b[start:off], 0), off
        if n > 0:
            raw = b[start:off + n]
            return cls(raw[4:-1].decode('utf-8', 'replace'), raw, n), off + n
        m = -n
        raw = b[start:off + m * 2]
        return cls(raw[4:-2].decode('utf-16-le', 'replace'), raw, n), off + m * 2

    @classmethod
    def make(cls, text, like=None):
        """新建字符串；like 用于对齐编码（None/ANSI 一律用 ANSI，除非含中文）。"""
        utf16 = False
        if like is not None:
            utf16 = (like.n < 0)
        if not utf16:
            try:
                a = text.encode('ascii')
            except UnicodeEncodeError:
                utf16 = True
        if utf16:
            u = text.encode('utf-16-le')
            return cls(text, struct.pack('<i', -(len(u) // 2 + 1)) + u + b'\x00\x00', -(len(u) // 2 + 1))
        a = text.encode('ascii')
        return cls(text, struct.pack('<i', len(a) + 1) + a + b'\x00', len(a) + 1)

    def set(self, text):
        s = Str.make(text, self)
        self.text, self.raw, self.n = s.text, s.raw, s.n

    def bytes(self):
        return self.raw


class Entry(object):
    __slots__ = ('key', 'hash', 'text', 'is_new')

    def __init__(self, key, h, text, is_new=False):
        self.key = key
        self.hash = h
        self.text = text
        self.is_new = is_new


class LocRes(object):
    def __init__(self):
        self.path = ''
        self.raw = b''
        self.start = 0
        self.end = 0
        self.count_off = 0
        self.count_orig = 0
        self.minus_one = False
        self.trailer = b''
        self.entries = []

    # -------------------------------------------------------------- 读
    @classmethod
    def load(cls, path):
        b = open(path, 'rb').read()
        obj = cls()
        obj.path = path
        obj.raw = b
        found = obj._find_layout(b)
        if not found:
            raise ValueError('不是能识别的 locres（找不到 count/entry 边界）: %s' % path)
        cnt_off, start, cnt, entries, end = found
        obj.count_off = cnt_off
        obj.start = start
        obj.end = end
        obj.count_orig = cnt
        obj.entries = entries
        obj.trailer = b[end:]
        obj.minus_one = (len(entries) == cnt + 1)
        return obj

    @staticmethod
    def _read_entries(b, start, limit):
        """从 start 贪心读条目，读到读不动为止。返回 (entries, end)。"""
        off = start
        rows = []
        while off < limit:
            try:
                key, noff = Str.read(b, off)
                if noff + 4 > limit:
                    break
                h = u32(b, noff)
                txt, end = Str.read(b, noff + 4)
                if end > limit:
                    break
            except Exception:
                break
            off = end
            rows.append(Entry(key, h, txt))
        return rows, off

    def _find_layout(self, b):
        n = len(b)
        for cnt_off in (8, 10, 12, 6, 4, 14, 16):
            if cnt_off + 4 > n:
                continue
            cnt = u32(b, cnt_off)
            if not (0 < cnt <= 500000):
                continue
            for start in (cnt_off + 4, cnt_off + 6, cnt_off + 8):
                rows, end = self._read_entries(b, start, n)
                if not rows:
                    continue
                left = n - end
                if left < 0 or left > 64:
                    continue
                if len(rows) in (cnt, cnt + 1):
                    return cnt_off, start, cnt, rows, end
        return None

    # -------------------------------------------------------------- 写
    def build(self, entries=None, count=None):
        rows = self.entries if entries is None else entries
        out = bytearray(self.raw[:self.start])
        for e in rows:
            out += e.key.bytes()
            out += struct.pack('<I', e.hash)
            out += e.text.bytes()
        out += self.trailer
        if count is None:
            cnt = len(rows) - 1 if self.minus_one else len(rows)
        else:
            cnt = count
        struct.pack_into('<I', out, self.count_off, cnt)
        return bytes(out)

    def save(self, path):
        data = self.build()
        with open(path, 'wb') as f:
            f.write(data)
        return len(data)

    # -------------------------------------------------------------- 操作
    def index(self):
        return dict((e.key.text, e) for e in self.entries)

    def set_text(self, key, text):
        e = self.index().get(key)
        if not e:
            return False
        e.text.set(text)
        return True

    def add(self, key, text):
        if not HEX32.match(key):
            raise ValueError('key 不是 32 位 hex: %r' % key)
        if key in self.index():
            return False
        k = Str.make(key, like=Str.make('A' * 32))       # 新 key 一律 ANSI
        t = Str.make(text, like=Str.make('A'))
        self.entries.append(Entry(k, 0, t, is_new=True))
        return True

    def stats(self):
        cn = 0
        empty = 0
        for e in self.entries:
            t = e.text.text
            if not t.strip():
                empty += 1
            elif any(u'\u4e00' <= c <= u'\u9fff' for c in t):
                cn += 1
        return {'entries': len(self.entries), 'cn': cn, 'empty': empty,
                'version': i32(self.raw, 0) if len(self.raw) >= 4 else -1,
                'start': self.start, 'count_off': self.count_off,
                'count_field': self.count_orig}


# ------------------------------------------------------------------ CSV


def read_csv(path):
    """读 key,source,target（也接受 2 列或 tab 分隔）。返回 [(key, src, tgt)]。"""
    raw = open(path, 'rb').read()
    if raw[:2] == b'\xff\xfe':
        text = raw.decode('utf-16', 'replace')
    elif raw[:3] == b'\xef\xbb\xbf':
        text = raw[3:].decode('utf-8', 'replace')
    else:
        text = raw.decode('utf-8', 'replace')
    if not text.strip():
        return []
    first = text.splitlines()[0]
    delim = '\t' if ('\t' in first and ',' not in first) else ','
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    out = []
    for idx, r in enumerate(rows):
        if not r:
            continue
        k = r[0].strip()
        if idx == 0 and k.lower() in ('key', 'id', 'keys'):
            continue                      # 表头
        k = k.lstrip('/')
        if '/' in k:
            k = k.rsplit('/', 1)[-1]      # namespace/key -> key
        if not k:
            continue
        src = r[1] if len(r) > 1 else ''
        tgt = r[2] if len(r) > 2 else ''
        out.append((k, src, tgt))
    return out


def write_csv(path, rows, with_source=True):
    with io.open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL, lineterminator='\r\n')
        if with_source:
            w.writerow(['key', 'source', 'target'])
        else:
            w.writerow(['key', 'target'])
        for row in rows:
            w.writerow(row)


# ------------------------------------------------------------------ scan


def looks_ok(s):
    if len(s) < 2:
        return False
    for ch in s:
        o = ord(ch)
        if o < 0x20 and ch not in '\n\r\t':
            return False
    return True


def scan_bytes(buf):
    """抽 'int32 33' + 32 hex + \\0 + FString 这种带 key 的 FText。"""
    hits = []
    pat = struct.pack('<i', 33)
    pos = 0
    n = len(buf)
    while True:
        i = buf.find(pat, pos)
        if i < 0:
            break
        pos = i + 1
        kstart = i + 4
        if kstart + 33 > n:
            break
        raw = buf[kstart:kstart + 32]
        if buf[kstart + 32] != 0:
            continue
        try:
            key = raw.decode('ascii')
        except UnicodeDecodeError:
            continue
        if not HEX32.match(key):
            continue
        off = kstart + 33
        try:
            s, off = Str.read(buf, off)
        except Exception:
            continue
        if looks_ok(s.text):
            hits.append((key, s.text, i, off))
    return hits


TEXT_EXT = ('.uexp', '.uasset', '.umap')


def iter_files(root):
    if os.path.isfile(root):
        yield root
        return
    for dp, dn, fn in os.walk(root):
        for f in fn:
            if f.lower().endswith(TEXT_EXT):
                yield os.path.join(dp, f)


# ------------------------------------------------------------------ 子命令


def cmd_build(a):
    """从 CSV 或资产目录，**从零生成**一个新 locres（不依赖底包）。"""
    if a.from_assets:
        rows = []
        seen = set()
        files = list(iter_files(a.from_assets))
        for fp in files:
            try:
                data = open(fp, 'rb').read()
            except Exception:
                continue
            for (key, text, _off, _end) in scan_bytes(data):
                k = key.strip().lower()
                if k in seen:
                    continue
                seen.add(k)
                rows.append((k, text, ''))
        print('扫了 %d 个资产，抓到 %d 条唯一 key' % (len(files), len(rows)))
    else:
        rows = read_csv(a.csv)
        print('CSV 读到 %d 行' % len(rows))
    if not rows:
        print('没有可写的内容。')
        return 1

    if a.template:
        tpl = LocRes.load(a.template)
        base = LocRes()
        base.raw = tpl.raw
        base.start = tpl.start
        base.count_off = tpl.count_off
        base.minus_one = tpl.minus_one
        base.trailer = tpl.trailer
        idx = tpl.index()
        print('模板: %s（%d 条，header %d B，trailer %d B）'
              % (os.path.basename(a.template), len(tpl.entries), tpl.start, len(tpl.trailer)))
    else:
        base = LocRes()
        base.raw = DEFAULT_HEADER
        base.start = 12
        base.count_off = 8
        base.minus_one = False                      # 命名空间记录不算在 count 里，单独补
        base.trailer = b'' if a.no_namespace else DEFAULT_TRAILER
        idx = {}
        print('模板: 无（内置头 12 B / 尾 %d B / 命名空间记录 %s）'
              % (len(base.trailer), '不加' if a.no_namespace else '补 UMG'))

    out = []
    added = upd = skipped = 0
    for key, src_text, tgt in rows:
        text = tgt.strip() or src_text.strip()
        if not text:
            skipped += 1
            continue
        k = (key or '').strip().lower()
        if not k:
            skipped += 1
            continue
        e = idx.get(k)
        if e is not None:
            e.text.set(text)
            out.append(e)
            upd += 1
        else:
            out.append(Entry(Str.make(k), 0, Str.make(text)))
            added += 1
    base.entries = out
    if (not a.template) and (not a.no_namespace):
        data = base.build(out + [Entry(Str.make(NS_KEY), NS_HASH, Str.make(NS_TEXT))],
                          count=len(out))
        with open(a.out, 'wb') as f:
            f.write(data)
        size = len(data)
    else:
        size = base.save(a.out)
    print('写成 %d 条（新建 %d / 复用模板 %d / 跳过 %d）-> %s (%d B)'
          % (len(out), added, upd, skipped, a.out, size))

    chk = LocRes.load(a.out)
    same = chk.build() == open(a.out, 'rb').read()
    print('自检: 条数 %d，回读重建 %s' % (len(chk.entries), 'OK' if same else '不一致!'))
    if a.print_first:
        for e in chk.entries[:a.print_first]:
            print('  %s = %s' % (e.key.text, e.text.text[:60]))
    return 0 if same else 1

def find_game_paks(start):
    """从 locres / 游戏目录 / 任意子目录往上找 Content\\Paks。"""
    cur = os.path.abspath(start)
    if os.path.isfile(cur):
        cur = os.path.dirname(cur)
    for _ in range(6):
        for cand in (os.path.join(cur, 'Content', 'Paks'),
                     os.path.join(cur, 'Paks'),
                     cur if cur.lower().endswith('paks') else ''):
            if cand and os.path.isdir(cand):
                return cand
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return ''


def cmd_pack(a):
    """把 locres 打成能直接丢进 Content\\Paks 的 pak（路径/UEngine 版本/挂载点全按真实包来）。"""
    if not os.path.isfile(a.locres):
        print('找不到 locres: %s' % a.locres)
        return 1
    repak = a.repak or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'repak', 'repak.exe')
    repak = os.path.abspath(repak)
    if not os.path.isfile(repak):
        repak = r'F:\模型\repak\repak.exe'
    if not os.path.isfile(repak):
        print('找不到 repak.exe（用 --repak 指定）')
        return 1

    project = a.project.strip('/')
    culture = a.culture.strip()
    virt = '%s/Content/Localization/Game/%s/Game.locres' % (project, culture)

    stage = a.work or os.path.join(os.environ.get('TEMP', '.'), '_lc_pack_%d' % os.getpid())
    if os.path.isdir(stage):
        shutil.rmtree(stage, ignore_errors=True)
    inner = os.path.join(stage, *virt.split('/')[:-1])
    os.makedirs(inner)
    dst = os.path.join(inner, 'Game.locres')
    shutil.copyfile(a.locres, dst)
    print('暂存: %s' % dst)
    print('包内路径: %s   （引擎就是按这个路径找的，名字必须叫 Game.locres）' % virt)

    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.locres)),
                                a.pak_name or 'CN_Build_P.pak')
    if os.path.exists(out):
        os.remove(out)
    cmd = [repak, 'pack', '-m', a.mount, '--version', a.version, stage, out]
    print('执行: %s' % ' '.join(cmd))
    import subprocess
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.stdout.strip():
        print(r.stdout.strip()[:800])
    if r.returncode != 0:
        print('repak 失败 (exit=%d): %s' % (r.returncode, (r.stderr or '')[:400]))
        return 1
    if not os.path.exists(out):
        print('repak 说成功但没产物，检查参数')
        return 1
    size = os.path.getsize(out)
    print('打好: %s  (%d B)' % (out, size))

    # 列出包内条目，确认路径真的对
    r2 = subprocess.run([repak, 'list', out], capture_output=True, text=True)
    got = [ln.strip() for ln in (r2.stdout or '').splitlines() if 'Game.locres' in ln]
    print('包内条目: %s' % (got[0] if got else '（没看到 Game.locres，异常）'))
    ok = bool(got) and virt.replace('/', '\\') in got[0].replace('/', '\\')

    if a.deploy:
        paks = a.game and find_game_paks(a.game) or ''
        if not paks:
            print('没找到游戏的 Content\\Paks（用 --game 指定游戏目录）')
            return 1
        target = os.path.join(paks, os.path.basename(out))
        if os.path.exists(target):
            stamp = time.strftime('%Y%m%d%H%M%S')
            bak = target + '.bak.' + stamp
            os.replace(target, bak)
            print('旧包已备份: %s' % bak)
        shutil.copyfile(out, target)
        print('已部署: %s' % target)
        sigs = [f for f in os.listdir(paks) if f.lower().endswith('.sig')]
        if sigs:
            print('提示: 这游戏的 Paks 里有 .sig（%s）—— 未签名 pak 需要绕签名（-fileopenlog / raosig 代理 DLL），否则照样不生效。' % ', '.join(sigs))
    else:
        print('（没加 --deploy，只出了 pak 文件）')

    shutil.rmtree(stage, ignore_errors=True)
    return 0 if ok else 1

def cmd_info(a):
    lr = LocRes.load(a.locres)
    st = lr.stats()
    print('文件      : %s' % a.locres)
    print('大小      : %d B' % len(lr.raw))
    print('版本字段  : %d' % st['version'])
    print('头部       : %s' % lr.raw[:lr.start].hex(' '))
    print('count@%d = %d  (实际 %d 条, minus_one=%s)'
          % (lr.count_off, lr.count_orig, st['entries'], lr.minus_one))
    print('含中文    : %d' % st['cn'])
    print('空译文    : %d' % st['empty'])
    k0, t0 = lr.entries[0].key.text, lr.entries[0].text.text
    print('第一条    : %s = %r' % (k0, t0[:60]))
    return 0


def cmd_export(a):
    lr = LocRes.load(a.locres)
    rows = [(e.key.text, e.text.text, e.text.text) for e in lr.entries]
    write_csv(a.csv, rows)
    print('已导出 %d 条 -> %s' % (len(rows), a.csv))
    return 0


def cmd_import(a):
    lr = LocRes.load(a.base)
    rows = read_csv(a.csv)
    upd = new = skip = fb = 0
    idx = lr.index()
    for key, src, tgt in rows:
        if not tgt.strip():
            if a.skip_empty:
                skip += 1
                continue
            if not src.strip():
                skip += 1
                continue
            tgt = src.strip()
            fb += 1
        e = idx.get(key)
        if e is not None:
            if e.text.text != tgt:
                e.text.set(tgt)
                upd += 1
        elif a.allow_new:
            try:
                lr.add(key, tgt)
                new += 1
            except ValueError:
                skip += 1
    size = lr.save(a.out)
    extra = ('，其中 %d 条空译文回落原文' % fb) if fb else ''
    print('更新 %d 条 / 新增 %d 条 / 跳过 %d 条%s -> %s (%d B, 共 %d 条)'
          % (upd, new, skip, extra, a.out, size, len(lr.entries)))
    return 0


def cmd_merge(a):
    base = read_csv(a.base)
    add = read_csv(a.add)
    out = []
    seen = set()
    for k, s, t in base:
        out.append((k, s, t))
        seen.add(k)
    n = 0
    for k, s, t in add:
        if k in seen:
            continue
        out.append((k, s, t))
        seen.add(k)
        n += 1
    write_csv(a.out, out)
    print('合并 %d + %d（新增 %d）-> %s' % (len(base), len(add), n, a.out))
    return 0



def cmd_verify(a):
    lr = LocRes.load(a.locres)
    bad = []
    seen = {}
    dup = 0
    for e in lr.entries:
        k = e.key.text
        if not HEX32.match(k):
            bad.append(k)
        if k in seen:
            dup += 1
        seen[k] = 1
    st = lr.stats()
    print('条数      : %d' % st['entries'])
    print('唯一 key  : %d  (重复 %d)' % (len(seen), dup))
    print('非法 key  : %d' % len(bad))
    print('含中文    : %d (%.1f%%)' % (st['cn'], 100.0 * st['cn'] / max(1, st['entries'])))
    print('空译文    : %d' % st['empty'])
    if a.csv:
        rows = read_csv(a.csv)
        missing = [k for k, _s, t in rows if t.strip() and k not in seen]
        print('CSV 有但 locres 没有: %d 条' % len(missing))
        for k in missing[:10]:
            print('   %s' % k)
    print('重建校验  : %s' % ('OK' if lr.build() == lr.raw else 'FAIL（会改字节，别用）'))
    return 0 if lr.build() == lr.raw else 3


# ------------------------------------------------------------------ v1.0 兼容


def find_repak(extra=None):
    cands = [extra] if extra else []
    here = os.path.dirname(os.path.abspath(__file__))
    cands += [os.path.join(here, 'repak.exe'), os.path.join(here, 'bin', 'repak.exe'),
              r'F:\模型\repak\repak.exe', r'F:\模型\repak\repak']
    for c in cands:
        if c and os.path.isfile(c):
            return c
    import shutil
    return shutil.which('repak')


def run(cmd, timeout=300):
    import subprocess
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
                           creationflags=(0x08000000 if IS_WIN else 0))
        return p.returncode, p.stdout.decode('utf-8', 'replace')
    except Exception as e:
        return -1, 'EXC: %s' % e


def human(n):
    for u in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return '%.1f %s' % (n, u) if u != 'B' else '%d B' % n
        n /= 1024.0
    return '%.1f TB' % n


def find_exe(game):
    game = os.path.abspath(game)
    if os.path.isfile(game):
        return game, '直接指定'
    best = None
    for dp, dn, fn in os.walk(game):
        if dp[len(game):].count(os.sep) > 5:
            dn[:] = []
            continue
        for f in fn:
            if not f.lower().endswith('.exe'):
                continue
            p = os.path.join(dp, f)
            if 'shipping' in f.lower():
                return p, 'Shipping 本体'
            if 'crashreport' in f.lower() or 'eac' in f.lower():
                continue
            if best is None or os.path.getsize(p) > os.path.getsize(best):
                best = p
    return best, '最大 exe'


def find_paks(game):
    game = os.path.abspath(game)
    if os.path.isfile(game):
        game = os.path.dirname(game)
    paks_dir = None
    for dp, dn, fn in os.walk(game):
        if dp[len(game):].count(os.sep) > 6:
            dn[:] = []
            continue
        if os.path.basename(dp).lower() == 'paks':
            paks_dir = dp
            break
    if not paks_dir:
        return None, [], [], []
    paks, utocs, sigs = [], [], []
    for f in sorted(os.listdir(paks_dir)):
        p = os.path.join(paks_dir, f)
        if not os.path.isfile(p):
            continue
        low = f.lower()
        (paks if low.endswith('.pak') else utocs if low.endswith('.utoc') else sigs if low.endswith('.sig') else []).append(p)
    return paks_dir, paks, utocs, sigs


LOCRES_RE = re.compile(r'(?i)(?:^|/)([^/]+)/content/localization/([^/]+)/([^/]+)/([^/]+)\.locres$')


def cmd_check(a):
    game = a.game
    repak = find_repak(a.repak)
    print('=' * 62)
    print(' LocCheck v2.2   %s' % game)
    print('=' * 62)
    exe, why = find_exe(game)
    if not exe:
        print('[!] 没找到 exe')
        return 2
    data = open(exe, 'rb').read()
    m = re.search(rb'(\+\+UE[45]\+Release)-([0-9]+\.[0-9]+)', data)
    ver = m.group(2).decode() if m else None
    print('exe        : %s (%s, %s)' % (exe, human(os.path.getsize(exe)), why))
    print('引擎       : %s' % (('UE ' + ver) if ver else '没读到'))
    paks_dir, paks, utocs, sigs = find_paks(game)
    print('Paks       : %s' % (paks_dir or '没找到'))
    print('pak/utoc/sig: %d / %d / %d' % (len(paks), len(utocs), len(sigs)))
    if not repak:
        print('[!] 没 reprank，跳过 pak 内容检查')
        return 0
    found = []
    for p in paks:
        cmd = [repak, '-a', a.key, 'list', p] if a.key else [repak, 'list', p]
        rc, out = run(cmd)
        if rc != 0:
            continue
        for line in out.splitlines():
            mm = LOCRES_RE.search(line.strip())
            if mm:
                found.append((os.path.basename(p), mm.group(2), mm.group(3)))
    if found:
        print('结论       : 【可用】找到 %d 个 locres' % len(found))
        for pak, target, culture in found[:10]:
            print('   %-24s %s/%s' % (pak, target, culture))
    else:
        print('结论       : 【待验】pak 里没有 locres，先用散装探针试')
    if sigs:
        print('提示       : 有 .sig，补丁 pak 不挂载时先试 -fileopenlog')
    return 0


def cmd_font(a):
    """把 TTF/OTF 直接做成引擎能吃的 .ufont（UE4 的 UFontFace 就是裸字体字节）"""
    src = a.font
    if not os.path.isfile(src):
        print("找不到字体文件: %s" % src)
        return 2
    with open(src, "rb") as f:
        data = f.read()
    head = data[:4]
    if head not in (b"\x00\x01\x00\x00", b"OTTO", b"ttcf", b"wOFF", b"wOF2", b"true"):
        print("不是可识别的字体（头 %s），支持 ttf / otf / ttc / woff" % head.hex())
        return 3
    stem = os.path.splitext(os.path.basename(src))[0]
    name = (a.name or stem).strip()
    if not name.lower().endswith(".ufont"):
        name += ".ufont"
    outdir = a.out or os.path.dirname(os.path.abspath(src))
    if outdir and not os.path.isdir(outdir):
        os.makedirs(outdir)
    out = os.path.join(outdir, name)
    with open(out, "wb") as f:
        f.write(data)
    print("字体: %s (%s B, 头 %s)" % (os.path.basename(src), format(len(data), ","), head.hex()))
    print("输出: %s" % out)
    print("提示: 这个 .ufont 直接放进 Content 对应目录即可，UE4 的 UFontFace 资产就是裸字体字节")
    return 0


def main():
    ap = argparse.ArgumentParser(prog='loccheck', description='UE locres 工具链 v2.2')
    sub = ap.add_subparsers(dest='cmd')

    p = sub.add_parser('build', help='从 CSV 或资产目录从零生成新 locres')
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--csv', help='key,source,target 的 CSV')
    g.add_argument('--from-assets', dest='from_assets', help='游戏目录 / uexp / uasset（直接扫文本）')
    p.add_argument('--out', required=True)
    p.add_argument('--template', help='拿一个现成 locres 当 header/trailer 模板（强烈建议）')
    p.add_argument('--print-first', dest='print_first', type=int, default=0)
    p.add_argument('--no-namespace', dest='no_namespace', action='store_true',
                   help='不补末尾的 UMG 命名空间记录（默认补，真实文件都有）')

    pf = sub.add_parser('font', help='把 ttf/otf 做成 .ufont')
    pf.add_argument('--font', required=True, help='ttf / otf / ttc / woff 文件')
    pf.add_argument('--name', help='输出文件名（默认取字体名），自动补 .ufont')
    pf.add_argument('--out', help='输出目录（默认跟字体同目录）')
    pf.set_defaults(func=cmd_font)

    p = sub.add_parser('info', help='看 locres 头/条数/中文率')
    p.add_argument('locres')

    p = sub.add_parser('export', help='locres -> csv')
    p.add_argument('locres')
    p.add_argument('csv')

    p = sub.add_parser('import', help='csv -> locres（默认允许新增 key）')
    p.add_argument('base', help='底包 locres')
    p.add_argument('csv')
    p.add_argument('out')
    p.add_argument('--no-new', dest='allow_new', action='store_false', help='只更新已有 key')
    p.add_argument('--skip-empty', dest='skip_empty', action='store_true',
                   help='空译文直接跳过（默认：空译文回落原文，保证 key 存在）')

    p = sub.add_parser('merge', help='两个 csv 合并')
    p.add_argument('base')
    p.add_argument('add')
    p.add_argument('-o', dest='out', required=True)


    p = sub.add_parser('verify', help='自检')
    p.add_argument('locres')
    p.add_argument('--csv')

    p = sub.add_parser('pack', help='把 locres 打成能丢进 Content\\Paks 的 pak')
    p.add_argument('locres')
    p.add_argument('--out')
    p.add_argument('--pak-name', dest='pak_name', default='CN_Build_P.pak')
    p.add_argument('--project', default='DeltaZone', help='工程名（pak 内第一段路径，默认 DeltaZone）')
    p.add_argument('--culture', default='en', help='文化目录：en / zh-Hans')
    p.add_argument('--mount', default='../../../')
    p.add_argument('--version', default='V11')
    p.add_argument('--repak')
    p.add_argument('--game', help='游戏目录（--deploy 时用，自动找 Content\\Paks）')
    p.add_argument('--deploy', action='store_true', help='直接拷进游戏的 Content\\Paks（旧的自动备份）')
    p.add_argument('--work', help='暂存目录（默认临时目录）')

    p = sub.add_parser('check', help='体检：这游戏能不能用 locres')
    p.add_argument('--game', required=True)
    p.add_argument('--repak')
    p.add_argument('--key')

    a = ap.parse_args()
    table = {'build': cmd_build, 'info': cmd_info, 'export': cmd_export, 'import': cmd_import,
             'merge': cmd_merge, 'verify': cmd_verify, 'check': cmd_check, 'pack': cmd_pack,
             'font': cmd_font}
    if a.cmd not in table:
        ap.print_help()
        return 1
    if IS_WIN:
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    return table[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())
