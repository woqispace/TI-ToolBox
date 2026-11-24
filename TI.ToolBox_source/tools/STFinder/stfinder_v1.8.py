#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stfinder.py —— 在 UE 游戏资产里找"存文本的东西"（StringTable / DataTable / 带 key 的 FText）

为什么需要它：
    有些游戏根本不加载 locres（实测：引擎从不打开 Content/Localization/**/*.locres），
    这时汉化只能改资产本身（uasset/uexp）。这个工具负责：
        1) 从 pak（或已解包目录）里挑出"可能存文本"的资产
        2) 逐个资产统计数据（FText 命中数、可读字符串数、评分）
        3) 按评分把最值得翻的资产 + 它们的 uasset/uexp 一起复制出来

只用标准库。pak 相关操作调用外部 repak.exe。

用法：
    # A. 已有解包目录（最快，推荐先这样）
    python stfinder.py scan --dir D:\\...\\dz_unpack --out report.tsv

    # B. 直接扫 pak（需要 repak.exe；加密 pak 要 --key）
    python stfinder.py scan --pak X:\\game.pak --key 0xA1E2... --work D:\\tmp\\unp --out report.tsv
    python stfinder.py scan --pak X:\\game.pak --names F:\\模型\\xxx_pak_list.txt --work ... 

    # C. 按报告把资产抽出来
    python stfinder.py extract --report report.tsv --min-score 40 --out D:\\out\\assets

    # D. 只统计某个 uexp
    python stfinder.py one --file D:\\...\\GameUi.uexp

评分规则（score）：
    FText（len==33 + 32 位 hex key + 紧随其后的正文）  每处 +3
    可读 FString（长度 2..400、可打印率 >=0.85、含空格或大写字母） 每处 +1
    路径/类名类字符串（/Game/、/Script/、.uasset、纯小写标识符）不计分
"""

import argparse
import io
import json
import os
import re
import struct
import subprocess
import sys

# ---------------------------------------------------------------- 基础判定

HEX32 = re.compile(rb'^[0-9a-fA-F]{32}$')
PRINTABLE = set(range(0x20, 0x7F))


def is_mostly_printable(buf, threshold=0.85):
    if not buf:
        return False
    ok = sum(1 for b in buf if b in PRINTABLE or b in (0x09, 0x0A, 0x0D))
    return ok / float(len(buf)) >= threshold


def looks_like_noise(s):
    """过滤器：路径 / 类名 / GUID / 纯标识符 都不当文本计分。"""
    if not s:
        return True
    low = s.lower()
    if any(low.startswith(k) for k in
           ('/game/', '/script/', '/engine/', 'class ', 'object ',
            'softobjectpath', 'package ', 'assetregistry', 'bp_', 'wbp_')):
        return True
    if any(k in low for k in ('/game/', '/script/', '.uasset', '.uexp', '.umap')):
        return True
    if re.match(r'^[a-z0-9_]+$', s):          # 纯小写标识符
        return True
    if HEX32.match(s.encode('ascii', 'ignore')) is not None:
        return True
    if len(s) < 2:
        return True
    return False


def read_fstring(buf, off, utf16_lenient=True):
    """读一个 UE FString，返回 (text, next_off) 或 (None, off)。"""
    if off + 4 > len(buf):
        return None, off
    n = struct.unpack_from('<i', buf, off)[0]
    if n == 0:
        return '', off + 4
    if 0 < n <= 4096:
        end = off + 4 + n
        if end > len(buf):
            return None, off
        raw = buf[off + 4:end]
        if raw.endswith(b'\x00'):
            raw = raw[:-1]
        if not is_mostly_printable(raw, 0.8):
            return None, off
        return raw.decode('latin-1'), end
    if utf16_lenient and -4096 <= n < 0:
        cnt = -n
        end = off + 4 + cnt * 2
        if end > len(buf):
            return None, off
        raw = buf[off + 4:end]
        try:
            s = raw.decode('utf-16-le')
        except UnicodeDecodeError:
            return None, off
        s = s.rstrip('\x00')
        if not s:
            return None, off
        return s, end
    return None, off


# ---------------------------------------------------------------- 扫描


DEFAULT_PATH_EXCLUDES = ('\\Engine\\', '/Engine/', '\\Plugins\\', '/Plugins/', '\\__ExternalActors__\\', '\\__ExternalObjects__\\')
DEFAULT_NAME_EXCLUDES = r'^(M_|MI_|MF_|MPC_|T_|RT_|S_|SK_|SM_|PHYS_|PS_|P_)'

_CODE_NAME_RE = re.compile(r'^(?:[FUEA]|b[A-Z])[A-Z][A-Za-z0-9_]{2,}$')


def looks_like_code(s):
    """UE 反射名 / 资源路径 / 哈希这类"不是给人看的"字符串。"""
    t = s.strip()
    if not t:
        return True
    if _CODE_NAME_RE.match(t):
        return True
    low = t.lower()
    for bad in ('/game/', '/script/', '/engine/', '.uasset', '.uexp', '.umap', '__', 'default__'):
        if bad in low:
            return True
    if re.match(r'^[0-9a-fA-F]{16,}$', t):
        return True
    if re.match(r'^[A-Za-z0-9_]{24,}$', t) and '_' in t:
        return True
    return False


def scan_bytes(buf, weigh_names=True):
    """返回 (ftexts, bare)。

    ftexts: [(key, text, key_off, text_off)]  —— 带 32 位 hex key 的 FText（locres 能覆盖）
    bare  : [str]                             —— 没有 key 的裸 FString（locres 够不着，只能改 uexp）
    """
    ftexts = []
    used = []           # 已被 FText 正文占用的区间，收割裸串时跳过
    seen_key_off = set()
    # 1) 带 key 的 FText：int32 == 33，紧跟 32 位 hex（+ 结尾 NUL），再跟正文
    for m in re.finditer(rb'\x21\x00\x00\x00([0-9a-fA-F]{32})', buf):
        key_off = m.start()
        if key_off in seen_key_off:
            continue
        seen_key_off.add(key_off)
        key = m.group(1).decode('ascii')
        after = m.end()
        text, tnext = read_fstring(buf, after)
        if text is None:
            text, tnext = read_fstring(buf, after + 1)
        if text is None or looks_like_noise(text):
            continue
        ftexts.append((key, text, key_off, after))
        if tnext and tnext > after:
            used.append((after, tnext))

    # 2) 通用 FString 收割 —— 只保留"不属于任何 FText 正文"的裸串
    def _bare_ok(s):
        t = s.strip()
        if len(t) < 3:
            return False
        # 含控制字符 / NUL 的串是二进制碎片，不是文本
        for ch in s:
            o = ord(ch)
            if o < 0x20 and ch not in '\n\r\t':
                return False
            if o == 0x7f:
                return False
        if t[0] in ']})>#=/:\\,;-*':
            return False
        alnum = sum(1 for ch in t if ch.isalnum())
        if alnum < 3:
            return False
        if alnum / float(len(t)) < 0.6:
            return False
        # 单个 token（没有空格）里出现下划线 / 多个大写，多半是控件名或变量名
        if ' ' not in t and '\n' not in t:
            if '_' in t:
                return False
            uppers = sum(1 for ch in t if ch.isupper())
            if uppers >= 2:
                return False
        return True
    bare = []
    i = 0
    n = len(buf)
    while i + 5 < n:
        ln = struct.unpack_from('<i', buf, i)[0]
        if 3 <= ln <= 400:
            start = i + 4
            end = start + ln
            if end < n:
                in_ftext = False
                for a, b in used:
                    if a <= i < b:
                        in_ftext = True
                        break
                if in_ftext:
                    i = end
                    continue
                raw = buf[start:end]
                if raw.endswith(b'\x00') and is_mostly_printable(raw[:-1], 0.9):
                    try:
                        s = raw[:-1].decode('latin-1')
                    except Exception:
                        s = None
                    if s and not looks_like_noise(s) and not looks_like_code(s) and _bare_ok(s):
                        # 控件名 / 蓝图标记这类不是给人看的，剔掉
                        if re.match(r'^[A-Za-z][A-Za-z0-9]*_\d+$', s) or s.startswith('BPTYPE_'):
                            i = end
                            continue
                        multiword = (' ' in s) or ('\n' in s)
                        if (multiword or (weigh_names and any(c.isupper() for c in s))) and s not in bare:
                            bare.append(s)
                        i = end
                        continue
        i += 1
    return ftexts, bare


def analyze_file(path):
    with open(path, 'rb') as f:
        buf = f.read()
    weigh = path.lower().endswith('.uexp')
    ftexts, bare = scan_bytes(buf, weigh_names=weigh)
    return {
        'path': path,
        'size': len(buf),
        'ftexts': ftexts,      # 带 key（locres 可覆盖）
        'bare': bare,          # 无 key（只能改 uexp）
        'strings': bare,       # 旧字段名，保持兼容
        'score': len(ftexts) * 3 + len(bare),
    }


# ---------------------------------------------------------------- repak 辅助


def read_lines_any(path):
    """读文本清单，自动处理 UTF-8 / UTF-8-BOM / UTF-16LE（PowerShell 重定向常见）。"""
    with open(path, 'rb') as f:
        raw = f.read()
    if raw.startswith(b'\xff\xfe'):
        txt = raw[2:].decode('utf-16-le', 'replace')
    elif raw.startswith(b'\xef\xbb\xbf'):
        txt = raw[3:].decode('utf-8', 'replace')
    elif b'\x00' in raw[:200]:
        txt = raw.decode('utf-16-le', 'replace')
    else:
        txt = raw.decode('utf-8', 'replace')
    out, seen = [], set()
    for ln in txt.splitlines():
        ln = ln.strip()
        if not ln or ln in seen:
            continue
        seen.add(ln)
        out.append(ln)
    return out


def repak_exe(explicit=None):
    if explicit:
        return explicit
    for c in (r'F:\模型\repak\repak.exe', r'F:\模型\repak\repak.exe'.replace('F:', 'D:'),
              'repak.exe'):
        if os.path.isfile(c) or c == 'repak.exe':
            return c
    return 'repak.exe'


def repak_list(repak, pak, key=None):
    cmd = [repak] + (['-a', key] if key else []) + ['list', pak]
    p = subprocess.run(cmd, capture_output=True, text=True, errors='replace')
    if p.returncode != 0:
        sys.exit('repak list 失败: %s' % (p.stderr or p.stdout)[:400])
    return [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]


DEFAULT_INCLUDE = (
    'UI', 'Localization', 'Menu', 'Text', 'Dialogue', 'Quest', 'Data',
    'ST_', 'DT_', 'Item', 'Inventory', 'Codex', 'Journal', 'Tutorial',
)


def pick_candidates(paths, include_terms, max_files):
    terms = [t.lower() for t in include_terms]
    hits = []
    for p in paths:
        low = p.lower()
        if not (low.endswith('.uasset') or low.endswith('.uexp')):
            continue
        if terms and not any(t in low for t in terms):
            continue
        hits.append(p)
        if max_files and len(hits) >= max_files:
            break
    return hits


def unpack_subset(repak, pak, key, includes, work, strip_prefix='../../../'):
    os.makedirs(work, exist_ok=True)
    cmd = [repak] + (['-a', key] if key else []) + ['unpack', '-o', work,
                                                    '-s', strip_prefix, '-f']
    for inc in includes:
        cmd += ['-i', inc]
    cmd.append(pak)
    print('  repak unpack -i ...（%d 条过滤）' % len(includes))
    p = subprocess.run(cmd, capture_output=True, text=True, errors='replace')
    if p.returncode != 0:
        print('  [warn] repak unpack 返回 %s: %s' % (p.returncode, (p.stderr or p.stdout)[:300]))
    return work


# ---------------------------------------------------------------- 报告

def _flat(x):
    """把单元格压成单行：换行写成 \\n，制表符变空格（Excel 单元格里更好读）。"""
    s = str(x)
    s = s.replace('\r\n', '\\n').replace('\r', '\\n').replace('\n', '\\n')
    s = s.replace('\t', ' ')
    return s


def _delim_for(path):
    return ',' if str(path).lower().endswith('.csv') else '\t'


def write_table(path, header, rows):
    """写 CSV/TSV：自动选分隔符，UTF-8 带 BOM，csv 模块负责转义。"""
    import csv
    with io.open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, delimiter=_delim_for(path), lineterminator='\n',
                       quoting=csv.QUOTE_MINIMAL)
        w.writerow(header)
        for r in rows:
            w.writerow([_flat(c) for c in r])


def read_table(path):
    """读 CSV 或 TSV：按扩展名选分隔符，读不到就嗅探；返回 list[list[str]]（不含表头）。"""
    import csv
    delim = _delim_for(path)
    if not str(path).lower().endswith(('.csv', '.tsv')):
        with io.open(path, encoding='utf-8-sig', errors='replace') as f:
            head = f.readline()
        delim = ',' if head.count(',') > head.count('\t') else '\t'
    out = []
    with io.open(path, encoding='utf-8-sig', errors='replace', newline='') as f:
        rd = csv.reader(f, delimiter=delim)
        next(rd, None)
        for row in rd:
            if row:
                out.append(row)
    return out


def write_report(rows, out):
    """写三份：组合表 + 带 key 表 + 裸文本表。"""
    rows.sort(key=lambda r: (-r['score'], -r['size']))

    data = []
    for r in rows:
        samples = ' | '.join(t for _, t, _, _ in r['ftexts'][:3])
        if not samples:
            samples = ' | '.join(r['bare'][:3]) or '（无文本）'
        data.append([r['score'], len(r['ftexts']), len(r['bare']), r['size'],
                     r['path'], samples[:500]])
    write_table(out, ['score', 'keyed', 'bare', 'size', 'path', 'samples'], data)
    print('组合报告: %s（%d 行）' % (out, len(rows)))

    base, ext = os.path.splitext(str(out))
    ext = ext or '.csv'
    keyed_out = base + '_keyed' + ext
    bare_out = base + '_bare' + ext

    krows = []
    for r in sorted(rows, key=lambda r: (-len(r['ftexts']), -r['size'])):
        if not r['ftexts']:
            continue
        s = ' | '.join(t for _, t, _, _ in r['ftexts'][:4])
        krows.append([len(r['ftexts']), len(r['bare']), r['size'], r['path'], s[:500]])
    brows = []
    for r in sorted(rows, key=lambda r: (-len(r['bare']), -r['size'])):
        if not r['bare']:
            continue
        s = ' | '.join(r['bare'][:4])
        brows.append([len(r['bare']), len(r['ftexts']), r['size'], r['path'], s[:500]])

    write_table(keyed_out, ['keyed', 'bare', 'size', 'path', 'samples'], krows)
    write_table(bare_out, ['bare', 'keyed', 'size', 'path', 'samples'], brows)
    print('带 key 报告（locres 能覆盖）: %s（%d 行）' % (keyed_out, len(krows)))
    print('裸文本报告（只能改 uexp）  : %s（%d 行）' % (bare_out, len(brows)))
    return krows, brows


def print_top(rows, n=15):
    keyed = sorted(rows, key=lambda r: (-len(r['ftexts']), -r['size']))
    bare = sorted(rows, key=lambda r: (-len(r['bare']), -r['size']))

    print('\n=== A) 带 key 的 FText（locres / localization 能覆盖）===')
    print('%-7s %-7s %-11s %s' % ('keyed', 'bare', 'size', 'path'))
    print('-' * 100)
    shown = 0
    for r in keyed:
        if not r['ftexts']:
            continue
        print('%-7d %-7d %-11d %s' % (len(r['ftexts']), len(r['bare']), r['size'], r['path'][-82:]))
        shown += 1
        if shown >= n:
            break
    if shown == 0:
        print('（没有文件带 key）')

    print('\n=== B) 不带 key 的裸文本（locres 够不着，只能改 uexp）===')
    print('%-7s %-7s %-11s %s' % ('bare', 'keyed', 'size', 'path'))
    print('-' * 100)
    shown = 0
    for r in bare:
        if not r['bare']:
            continue
        print('%-7d %-7d %-11d %s' % (len(r['bare']), len(r['ftexts']), r['size'], r['path'][-82:]))
        shown += 1
        if shown >= n:
            break
    if shown == 0:
        print('（没有裸文本）')

    print()
    if keyed and keyed[0]['ftexts']:
        best = keyed[0]
        print('A 组样例（%s）:' % os.path.basename(best['path']))
        for key, text, koff, toff in best['ftexts'][:5]:
            print('  key=%s  off=0x%X  %r' % (key, koff, text[:80]))
    if bare and bare[0]['bare']:
        bestb = bare[0]
        print('B 组样例（%s）:' % os.path.basename(bestb['path']))
        for s in bestb['bare'][:5]:
            print('  str  %r' % s[:80])
    print()


# ---------------------------------------------------------------- 子命令

def cmd_one(args):
    r = analyze_file(args.file)
    print('文件   : %s' % r['path'])
    print('大小   : %d B' % r['size'])
    print('A 带 key 的 FText : %d 处   -> locres / localization 能覆盖' % len(r['ftexts']))
    print('B 不带 key 的裸串 : %d 条   -> locres 够不着，只能改 uexp' % len(r['bare']))
    print('评分   : %d' % r['score'])
    print('\n--- A) 带 key 的 FText（前 20）---')
    if r['ftexts']:
        for key, text, koff, toff in r['ftexts'][:20]:
            print('  0x%-8X %-34s %r' % (koff, key, text[:90]))
    else:
        print('  （无）')
    print('\n--- B) 不带 key 的裸串（前 20）---')
    if r['bare']:
        for s in r['bare'][:20]:
            print('  %r' % s[:90])
    else:
        print('  （无）')


def _path_excluded(p, subs):
    return any(x and x in p for x in subs)


def _name_excluded(fn, rx):
    return bool(rx and rx.match(fn))


def iter_assets(root, path_excludes=(), name_rx=None):
    for cur, _dirs, files in os.walk(root):
        for fn in files:
            if not fn.lower().endswith(('.uasset', '.uexp', '.umap')):
                continue
            p = os.path.join(cur, fn)
            if path_excludes and _path_excluded(p, path_excludes):
                continue
            if _name_excluded(fn, name_rx):
                continue
            yield p


def cmd_scan(args):
    rows = []
    if args.dir:
        print('扫描目录: %s' % args.dir)
        if getattr(args, 'no_exclude', False):
            pe, nr = (), None
        else:
            pe = tuple(args.exclude or DEFAULT_PATH_EXCLUDES)
            nr = re.compile(args.exclude_name) if getattr(args, 'exclude_name', None) else re.compile(DEFAULT_NAME_EXCLUDES)
        skipped = 0
        files = []
        for root_dir, _d, fns in os.walk(args.dir):
            for fn in fns:
                if not fn.lower().endswith(('.uasset', '.uexp', '.umap')):
                    continue
                p = os.path.join(root_dir, fn)
                if pe and _path_excluded(p, pe):
                    skipped += 1; continue
                if nr and _name_excluded(fn, nr):
                    skipped += 1; continue
                files.append(p)
        if skipped:
            print('  按规则跳过 %d 个（Engine/Plugins 目录 或 材质/贴图/音效等资产；--no-exclude 可关闭）' % skipped)
        print('  找到 %d 个资产文件' % len(files))
        for i, fp in enumerate(files, 1):
            try:
                rows.append(analyze_file(fp))
            except Exception as ex:
                print('  [skip] %s (%s)' % (fp, ex))
            if i % 200 == 0:
                print('  ...%d/%d' % (i, len(files)))
    else:
        repak = repak_exe(args.repak)
        print('pak: %s' % args.pak)
        if args.names and os.path.isfile(args.names):
            paths = read_lines_any(args.names)
            print('  路径清单: %s（%d 条，已去重）' % (args.names, len(paths)))
        else:
            paths = repak_list(repak, args.pak, args.key)
            print('  repak list: %d 条' % len(paths))
            if args.save_names:
                with io.open(args.save_names, 'w', encoding='utf-8', newline='\n') as f:
                    f.write('\n'.join(paths))
                print('  已保存清单: %s' % args.save_names)
        includes = args.include or list(DEFAULT_INCLUDE)
        cands = pick_candidates(paths, includes, args.max_files)
        print('  命中候选 %d 个（过滤词: %s）' % (len(cands), ','.join(includes[:8]) + '…'))
        if not cands:
            sys.exit('没有候选。放宽 --include 或去掉过滤。')
        dirs = sorted({p.rsplit('/', 1)[0] for p in cands})
        print('  涉及目录 %d 个，开始解包…' % len(dirs))
        work = args.work or os.path.join(os.path.dirname(os.path.abspath(args.pak)) or '.',
                                         '_stfinder_unpack')
        unpack_subset(repak, args.pak, args.key, dirs[:args.max_dirs], work)
        files = list(iter_assets(work))
        print('  解出 %d 个资产文件，开始分析…' % len(files))
        for fp in files:
            try:
                rows.append(analyze_file(fp))
            except Exception as ex:
                print('  [skip] %s (%s)' % (fp, ex))
    if getattr(args, 'all', False):
        rows = [r for r in rows if (len(r['ftexts']) + len(r['bare'])) > 0]
    else:
        rows = [r for r in rows if len(r['ftexts']) >= getattr(args, 'min_ftext', 1)]
        print('只保留有 key 的文件（--all 可看全部，含只有裸文本的）')
    print_top(rows, args.top)
    if args.out:
        write_report(rows, args.out)


def cmd_extract(args):
    """按报告把资产抽出来：uasset/umap 与 uexp 成对复制。"""
    out = args.out
    os.makedirs(out, exist_ok=True)
    rows = []
    for parts in read_table(args.report):
        if len(parts) < 5:
            continue
        try:
            score = int(parts[0])
        except ValueError:
            continue
        if score < args.min_score:
            continue
        rows.append((score, parts[4]))
    print('报告里 >= %d 分的资产: %d 个' % (args.min_score, len(rows)))
    copied, lonely = 0, 0
    for score, path in rows:
        stem = path
        for ext in ('.uasset', '.uexp', '.umap'):
            if stem.lower().endswith(ext):
                stem = stem[:-len(ext)]
                break
        # 成对：主体可能是 .uasset（普通资产）或 .umap（地图），都要试
        for ext in ('.uasset', '.umap', '.uexp'):
            src = stem + ext
            if not os.path.isfile(src):
                continue
            rel = os.path.relpath(src, args.root) if args.root else os.path.basename(src)
            dst = os.path.join(out, rel)
            d = os.path.dirname(dst)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(src, 'rb') as fr, open(dst, 'wb') as fw:
                fw.write(fr.read())
            copied += 1
        # 提示缺另一半
        has_head = os.path.isfile(stem + '.uasset') or os.path.isfile(stem + '.umap')
        has_uexp = os.path.isfile(stem + '.uexp')
        if not (has_head and has_uexp):
            lonely += 1
            if lonely <= 10:
                print('  [注意] 只有一半: %s' % os.path.basename(stem))
    print('已复制 %d 个文件到 %s' % (copied, out))
    if lonely:
        print('有 %d 个资产只找到一半（uasset/umap/uexp 缺一个）' % lonely)


def find_ftexts(data):
    """返回 [(keyoff, key_hex, lenoff, ln, enc, text)]，enc 为 'ansi' 或 'utf16'。"""
    out = []
    n = len(data)
    i = 0
    while True:
        j = data.find(b'\x21\x00\x00\x00', i)
        if j < 0 or j + 37 + 4 > n:
            break
        k = data[j + 4:j + 36]
        if data[j + 36] == 0 and all(chr(c) in '0123456789abcdefABCDEF' for c in k):
            p2 = j + 37
            ln = int.from_bytes(data[p2:p2 + 4], 'little', signed=True)
            if 0 < ln < 40000 and p2 + 4 + ln <= n:
                raw = data[p2 + 4:p2 + 4 + ln]
                if raw.endswith(b'\x00'):
                    body = raw.rstrip(b'\x00')
                    txt = ''
                    for _e in ('utf-8', 'gbk', 'latin-1'):
                        try:
                            txt = body.decode(_e)
                            break
                        except UnicodeDecodeError:
                            txt = ''
                    if txt and '\x00' not in txt:
                        out.append((j, k.decode('ascii'), p2, ln, 'ansi', txt))
                        i = p2 + 4 + ln
                        continue
            elif -40000 < ln < 0 and p2 + 4 + (-ln) * 2 <= n:
                raw = data[p2 + 4:p2 + 4 + (-ln) * 2]
                try:
                    txt = raw.decode('utf-16-le')
                except UnicodeDecodeError:
                    txt = ''
                txt = txt.rstrip('\x00')
                if txt and '\x00' not in txt:
                    out.append((j, k.decode('ascii'), p2, ln, 'utf16', txt))
                    i = p2 + 4 + (-ln) * 2
                    continue
        i = j + 4
    return out


def cmd_keys(args):
    """只导出带 key 的 FText -> locres 可直接 import 的 CSV（key,source,target）。"""
    if os.path.isdir(args.path):
        if getattr(args, 'no_exclude', False):
            pe, nr = (), None
        else:
            pe = tuple(DEFAULT_PATH_EXCLUDES)
            nr = re.compile(DEFAULT_NAME_EXCLUDES)
        targets = []
        for root_dir, _d, fns in os.walk(args.path):
            for fn in fns:
                if not fn.lower().endswith(('.uasset', '.uexp', '.umap')):
                    continue
                p = os.path.join(root_dir, fn)
                if pe and _path_excluded(p, pe):
                    continue
                if nr and _name_excluded(fn, nr):
                    continue
                targets.append(p)
    else:
        targets = [args.path]

    print('扫描 %d 个文件…' % len(targets))
    seen = {}
    for fp in targets:
        try:
            data = open(fp, 'rb').read()
        except Exception as ex:
            print('  [skip] %s (%s)' % (fp, ex))
            continue
        for (_koff, key, _p2, _ln, _enc, txt) in find_ftexts(data):
            if len(txt.strip()) < args.min_len:
                continue
            k = key.strip().lower()
            if k in seen or len(k) != 32:
                continue
            seen[k] = (txt.strip(), fp)
    rows = [[k, v[0], ''] for k, v in seen.items()]
    print('命中 %d 条唯一 key' % len(rows))
    for k, v in list(seen.items())[:args.top]:
        print('  %s  %s' % (k, v[0][:70]))
    if args.out:
        write_table(args.out, ['key', 'source', 'target'], rows)
        print('已写出 %d 行 -> %s（LocCheck 可直接 import）' % (len(rows), args.out))


def cmd_dump(args):
    """导出一个资产里的全部 FText：textoff / key / len / enc / text。"""
    data = open(args.file, 'rb').read()
    items = find_ftexts(data)
    print('文件 : %s' % args.file)
    print('大小 : %d B' % len(data))
    print('FText: %d 条' % len(items))
    if not items:
        print('没有找到 FText。')
        return
    data = [[('0x%X' % p2), key, ln, enc, txt] for (koff, key, p2, ln, enc, txt) in items]
    if args.out:
        write_table(args.out, ['textoff', 'key', 'len', 'enc', 'text'], data)
        print('已写出 %d 行 -> %s' % (len(data), args.out))
    else:
        print('  textoff\tkey\tlen\tenc\ttext')
        for row in data[:args.top]:
            print('  ' + '\t'.join(_flat(c) for c in row))


def cmd_apply(args):
    """按 TSV 回写：textoff 处是长度字段，改完内容长度字段不变。"""
    import shutil
    data = bytearray(open(args.file, 'rb').read())
    rows = []
    for parts in read_table(args.texts):
        if len(parts) < 5:
            continue
        try:
            ln_i = int(parts[2])
        except ValueError:
            continue
        # 文本里的 \\n 还原成真换行（_flat 写过）
        txt = parts[4].replace('\\n', '\n')
        rows.append((parts[0], parts[1], ln_i, parts[3], txt))
    print('待处理 %d 条' % len(rows))
    if not args.dry:
        shutil.copyfile(args.file, args.file + '.bak')
    ok = over = skipped = 0
    over_list = []
    for (off_s, key, ln, enc, text) in rows:
        if text == '':
            skipped += 1
            continue
        off = int(off_s, 16)
        if enc == 'ansi':
            cap = ln - 1
            try:
                payload = text.encode('gbk')
            except UnicodeEncodeError:
                print('  [跳过] 0x%X 无法 GBK 编码: %s' % (off, text))
                skipped += 1
                continue
            if len(payload) > cap:
                over += 1
                over_list.append((off, text, len(payload), cap))
                continue
            n = ln - 1 - len(payload)
            if n < 0:
                over += 1
                over_list.append((off, text, len(payload), ln - 1))
                continue
            data[off + 4:off + 4 + ln] = payload + b' ' * n + b'\x00'
        else:
            wcap = -ln - 1
            payload = text.encode('utf-16-le')
            if len(payload) // 2 > wcap:
                over += 1
                over_list.append((off, text, len(payload) // 2, wcap))
                continue
            need = -ln - 1 - (len(payload) // 2)
            if need < 0:
                over += 1
                over_list.append((off, text, len(payload) // 2, -ln - 1))
                continue
            data[off + 4:off + 4 + (-ln) * 2] = payload + (' '.encode('utf-16-le')) * need + b'\x00\x00'
        ok += 1
    if over_list:
        print('超长 %d 条（需缩短或走变长模式）：' % len(over_list))
        for (off, text, need, cap) in over_list[:20]:
            print('  0x%X  %s  需要 %d，可用 %d' % (off, text, need, cap))
    if ok and not args.dry:
        open(args.file, 'wb').write(bytes(data))
        print('已写入 %d 条（备份 .bak）' % ok)
        after = len(find_ftexts(open(args.file, 'rb').read()))
        flag = '' if after == len(rows) else '   <-- 数量不一致，请检查'
        print('自检：写前 %d 条 / 写后 %d 条%s' % (len(rows), after, flag))
    else:
        print('ok=%d 超长=%d 跳过=%d%s' % (ok, over, skipped, '（dry-run）' if args.dry else ''))


def cmd_clean(args):
    """清理临时解包目录 / 旧报告。"""
    import shutil
    targets = []
    if args.dir:
        for d in args.dir:
            if os.path.isdir(d):
                targets.append(d)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
        for name in os.listdir(base):
            full = os.path.join(base, name)
            if os.path.isdir(full) and (name.startswith('_work') or name.startswith('_stfinder')):
                targets.append(full)
        rep = os.path.join(base, 'reports')
        if os.path.isdir(rep) and getattr(args, 'reports', False):
            targets.append(rep)
    if not targets:
        print('没有要清理的目录。')
        return
    total = 0
    for t in targets:
        size = 0
        for cur, _d, fs in os.walk(t):
            for f in fs:
                try:
                    size += os.path.getsize(os.path.join(cur, f))
                except OSError:
                    pass
        shutil.rmtree(t, ignore_errors=True)
        total += size
        print('  已删 %s（%.1f MB）' % (t, size / 1048576.0))
    print('共释放 %.1f MB' % (total / 1048576.0))


def main():
    ap = argparse.ArgumentParser(description='找 UE 资产里的文本（StringTable / DataTable / 带 key 的 FText）')
    sub = ap.add_subparsers(dest='cmd', required=True)

    s1 = sub.add_parser('scan', help='扫描目录或 pak，出报告')
    s1.add_argument('--dir', help='已解包目录')
    s1.add_argument('--pak', help='pak 文件')
    s1.add_argument('--key', help='pak 的 AES key（加密 pak 需要，如 0xA1E2...）')
    s1.add_argument('--names', help='已有路径清单文件（跳过 repak list）')
    s1.add_argument('--save-names', help='把 repak list 结果存成文件')
    s1.add_argument('--include', nargs='*', help='路径包含词（默认 UI/Localization/Menu/Text/...）')
    s1.add_argument('--max-files', type=int, default=4000, help='候选文件上限，默认 4000')
    s1.add_argument('--max-dirs', type=int, default=400, help='解包目录上限，默认 400')
    s1.add_argument('--work', help='解包临时目录')
    s1.add_argument('--repak', help='repak.exe 路径')
    s1.add_argument('--out', help='报告输出（.csv 给 Excel，.tsv 也行）')
    s1.add_argument('--top', type=int, default=15, help='屏幕打印前 N 个')
    s1.add_argument('--all', action='store_true', help='连没有 FText 的文件也列出来（默认只列有 FText 的）')
    s1.add_argument('--min-ftext', type=int, default=1, help='至少多少条 FText 才进报告（默认 1）')
    s1.add_argument('--exclude', action='append', default=None, metavar='SUBSTR',
                    help='排除路径含该子串的资产，可重复（默认排除 Engine/Plugins 目录）')
    s1.add_argument('--exclude-name', default=None, metavar='REGEX',
                    help='排除文件名匹配该正则的资产（默认 M_/MI_/T_/S_/SK_/SM_ 等材质贴图音效）')
    s1.add_argument('--no-exclude', action='store_true', help='关闭上面两条默认排除')
    s1.set_defaults(func=cmd_scan)

    s2 = sub.add_parser('extract', help='按报告把资产抽出来')
    s2.add_argument('--report', required=True)
    s2.add_argument('--min-score', type=int, default=40)
    s2.add_argument('--root', help='资产所在根目录（报告里是绝对路径时可省略）')
    s2.add_argument('--out', required=True)
    s2.set_defaults(func=cmd_extract)

    s3 = sub.add_parser('one', help='只看一个文件')
    s3.add_argument('--file', required=True)
    s3.set_defaults(func=cmd_one)

    s4 = sub.add_parser('clean', help='清理临时解包目录')
    s4.add_argument('--dir', nargs='*', help='指定要删的目录（默认清工具目录下的 _work*）')
    s4.add_argument('--reports', action='store_true', help='连 reports 目录一起删')
    s4.set_defaults(func=cmd_clean)

    s5 = sub.add_parser('dump', help='把一个资产的 FText 全部导出成 TSV')
    s5.add_argument('--file', required=True)
    s5.add_argument('--out')
    s5.add_argument('--top', type=int, default=20)
    s5.set_defaults(func=cmd_dump)

    s6 = sub.add_parser('apply', help='按 TSV 回写 uexp（等长 GBK）')
    s6.add_argument('--file', required=True)
    s6.add_argument('--texts', required=True)
    s6.add_argument('--dry', action='store_true')
    s6.add_argument('--force', action='store_true')
    s6.set_defaults(func=cmd_apply)

    s7 = sub.add_parser('keys', help='只导带 key 的 FText -> locres 可直接 import 的 CSV')
    s7.add_argument('path', help='目录 / uexp / uasset')
    s7.add_argument('--out', required=True)
    s7.add_argument('--min-len', type=int, default=2, dest='min_len')
    s7.add_argument('--top', type=int, default=10)
    s7.add_argument('--no-exclude', action='store_true', dest='no_exclude')
    s7.set_defaults(func=cmd_keys)
    a = ap.parse_args()
    a.func(a)


if __name__ == '__main__':
    main()
