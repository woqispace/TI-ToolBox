#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""绕sig补丁生成器 (dllinject / sigpatch)

作用：给 x64 UE 游戏自动带上一个引擎命令行参数（典型：-fileopenlog），
      让引擎跳过 pak 签名校验，从而挂载我们自己打的未签名汉化 pak。

原理：读目标 exe 的导入表 -> 挑一个宿主 DLL -> 用同名代理 DLL 顶替它，
      代理里把每个导出都做成一条 `jmp [真实函数指针]` 的机器级桩，
      DllMain 里 LoadLibrary 系统原版拿到真实地址，并改写主模块 IAT 的
      KERNEL32!GetCommandLineW，让引擎读到追加了参数的命令行。

用法：
    python raosig.py list --exe "Yuna-Win64-Shipping.exe"
    python raosig.py build --exe "...\\Yuna-Win64-Shipping.exe" --host XAPOFX1_5 --arg=-fileopenlog --deploy
    python raosig.py uninstall --exe "...\\Yuna-Win64-Shipping.exe" --host XAPOFX1_5
"""
import argparse
import datetime
import io
import os
import shutil
import struct
import subprocess
import sys
import tempfile

REDIRECT_PREFIX = "zzh_"
VSWHERE = r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
VCVARS_CANDIDATES = [
    r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat",
    r"C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat",
    r"C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat",
    r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat",
    r"C:\Program Files\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvars64.bat",
    r"C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat",
]
SYSTEM32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
BAD_HOSTS = {
    "kernel32.dll", "kernelbase.dll", "user32.dll", "advapi32.dll", "ntdll.dll",
    "gdi32.dll", "ole32.dll", "oleaut32.dll", "shell32.dll", "shlwapi.dll",
    "msvcrt.dll", "ucrtbase.dll", "vcruntime140.dll", "combase.dll", "rpcrt4.dll",
    "dwmapi.dll",
}
# 这些 DLL 被大量其它 DLL 也依赖，顶替它们出错的代价太大，自动挑选时排到最后
RISKY_HOSTS = {
    "version.dll", "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll",
    "msvcp140_1.dll", "msvcp140_2.dll", "concrt140.dll", "vccorlib140.dll",
    "ws2_32.dll", "winmm.dll", "winhttp.dll", "crypt32.dll", "bcrypt.dll",
    "dbghelp.dll", "d3d11.dll", "dxgi.dll", "opengl32.dll", "d3d9.dll",
}


class PE:
    """最小 PE 解析：导入表 / 导出表。只处理 x64。"""

    def __init__(self, path):
        with open(path, "rb") as f:
            self.data = f.read()
        d = self.data
        if d[:2] != b"MZ":
            raise ValueError("不是 PE 文件: %s" % path)
        self.e_lfanew = struct.unpack_from("<I", d, 0x3C)[0]
        if d[self.e_lfanew:self.e_lfanew + 4] != b"PE\0\0":
            raise ValueError("PE 头损坏: %s" % path)
        coff = self.e_lfanew + 4
        (self.machine, self.nsec, _, _, _, self.optsize, self.chars) = struct.unpack_from("<HHIIIHH", d, coff)
        self.opt = coff + 20
        self.magic = struct.unpack_from("<H", d, self.opt)[0]
        self.pe32plus = (self.magic == 0x20B)
        if not self.pe32plus:
            raise ValueError("只支持 x64 PE: %s" % path)
        self.ddir = self.opt + 112
        self.sections = []
        sec_off = self.opt + self.optsize
        for i in range(self.nsec):
            name, vsize, vaddr, rsize, rptr = struct.unpack_from("<8sIIII", d, sec_off + i * 40)
            self.sections.append((vaddr, vsize, rptr, rsize))

    def rva2off(self, rva):
        for vaddr, vsize, rptr, rsize in self.sections:
            if vaddr <= rva < vaddr + max(vsize, rsize):
                return rptr + (rva - vaddr)
        return None

    def _dir(self, index):
        return struct.unpack_from("<II", self.data, self.ddir + 8 * index)

    def imports(self):
        rva, _ = self._dir(1)
        out = []
        if not rva:
            return out
        off = self.rva2off(rva)
        while True:
            ent = struct.unpack_from("<IIIII", self.data, off)
            if ent == (0, 0, 0, 0, 0):
                break
            name_off = self.rva2off(ent[3])
            end = self.data.index(b"\0", name_off)
            out.append(self.data[name_off:end].decode("latin1"))
            off += 20
        return out

    def ordinal_imports(self):
        """返回 {dll: [ordinal, ...]}：目标按【序号】导入的符号。
        代理 DLL 若只按名字导出，加载器会解析不到序号，进程直接起不来。"""
        rva, _ = self._dir(1)
        out = {}
        if not rva:
            return out
        off = self.rva2off(rva)
        while True:
            ent = struct.unpack_from("<IIIII", self.data, off)
            if ent == (0, 0, 0, 0, 0):
                break
            oft, _ts, _fwd, name_rva, ft = ent
            name_off = self.rva2off(name_rva)
            end = self.data.index(b"\0", name_off)
            dll = self.data[name_off:end].decode("latin1")
            thunk = oft or ft
            ords = []
            t = self.rva2off(thunk) if thunk else None
            if t is not None:
                while True:
                    v = struct.unpack_from("<Q", self.data, t)[0]
                    if v == 0:
                        break
                    if v & 0x8000000000000000:
                        ords.append(v & 0xFFFF)
                    t += 8
            if ords:
                out[dll] = ords
            off += 20
        return out

    def exports(self):
        rva, _ = self._dir(0)
        if not rva:
            return []
        off = self.rva2off(rva)
        if off is None:
            return []
        (_, _, _, _, _, base, nfuncs, nnames, _funcs, names_rva, ords_rva) = struct.unpack_from(
            "<IIHHIIIIIII", self.data, off)
        out = []
        for i in range(nnames):
            nrva = struct.unpack_from("<I", self.data, self.rva2off(names_rva) + 4 * i)[0]
            o = self.rva2off(nrva)
            end = self.data.index(b"\0", o)
            nm = self.data[o:end].decode("latin1")
            ordv = struct.unpack_from("<H", self.data, self.rva2off(ords_rva) + 2 * i)[0]
            out.append((base + ordv, nm))
        return out


def find_vcvars():
    env = os.environ.get("RAOSIG_VCVARS")
    if env and os.path.isfile(env):
        return env
    for p in VCVARS_CANDIDATES:
        if os.path.isfile(p):
            return p
    if os.path.isfile(VSWHERE):
        try:
            out = subprocess.run(
                [VSWHERE, "-latest", "-products", "*",
                 "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                 "-property", "installationPath"],
                capture_output=True, text=True, timeout=90).stdout.strip()
            if out:
                p = os.path.join(out, r"VC\Auxiliary\Build\vcvars64.bat")
                if os.path.isfile(p):
                    return p
        except Exception:
            pass
    return None


CPP_TEMPLATE = r'''// 由 绕sig补丁生成器 自动生成
#include <windows.h>

static const wchar_t* ARG   = L"__ARG__";
static const wchar_t* HOST  = L"__HOST__";
static const wchar_t* REALD = L"__REALDLL__";

static HINSTANCE g_real = 0;
static LPWSTR (WINAPI *g_realGCL)(void) = 0;
static HANDLE (WINAPI *g_realCFW)(LPCWSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES,
                                  DWORD, DWORD, HANDLE) = 0;
static wchar_t g_buf[8192];
static int g_logFiles = __LOGFILES__;

__DERIVED_POINTERS__

static void logline(const char* msg) {
    wchar_t path[MAX_PATH];
    DWORD n = GetTempPathW(MAX_PATH - 64, path);
    if (n == 0) return;
    lstrcatW(path, L"__LOGNAME__");
    HANDLE h = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                           NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) return;
    SetFilePointer(h, 0, NULL, FILE_END);
    DWORD w = 0;
    WriteFile(h, msg, (DWORD)lstrlenA(msg), &w, NULL);
    WriteFile(h, "\r\n", 2, &w, NULL);
    CloseHandle(h);
}

static LPWSTR WINAPI Hooked_GetCommandLineW(void) {
    LPWSTR real = g_realGCL ? g_realGCL() : NULL;
    if (!real) return real;
    int n = lstrlenW(real);
    if (n > 8000) return real;
    lstrcpynW(g_buf, real, 8000);
    if (wcsstr(g_buf, ARG) == NULL) {
        lstrcatW(g_buf, L" ");
        lstrcatW(g_buf, ARG);
    }
    return g_buf;
}

static void logw(const wchar_t* s) {
    char buf[1200];
    int n = WideCharToMultiByte(CP_ACP, 0, s, -1, buf, sizeof(buf) - 1, 0, 0);
    if (n <= 0) return;
    buf[n > 0 ? n - 1 : 0] = 0;
    logline(buf);
}

static int want_log(const wchar_t* name) {
    static const wchar_t* kExts[7] = { L".pak", L".sig", L".locres", L".locmeta",
                                       L".ucas", L".utoc", L".ufont" };
    int n = lstrlenW(name);
    if (n < 5) return 0;
    for (int i = 0; i < 7; ++i) {
        int m = lstrlenW(kExts[i]);
        if (n >= m && _wcsicmp(name + n - m, kExts[i]) == 0) return 1;
    }
    return 0;
}

static HANDLE WINAPI Hooked_CreateFileW(LPCWSTR name, DWORD acc, DWORD share,
                                        LPSECURITY_ATTRIBUTES sa, DWORD disp,
                                        DWORD flags, HANDLE tmpl) {
    if (g_logFiles && name && want_log(name)) {
        wchar_t line[1024];
        lstrcpynW(line, L"open ", 6);
        lstrcpynW(line + 5, name, 1000);
        logw(line);
    }
    if (!g_realCFW) return INVALID_HANDLE_VALUE;
    return g_realCFW(name, acc, share, sa, disp, flags, tmpl);
}


typedef HANDLE (WINAPI *FN_FFF)(LPCWSTR, LPWIN32_FIND_DATAW);
typedef HANDLE (WINAPI *FN_FFFE)(LPCWSTR, int, LPWIN32_FIND_DATAW, int, DWORD);
static FN_FFF  g_realFFF  = NULL;
static FN_FFFE g_realFFFE = NULL;

static int want_dir_log(const wchar_t* s) {
    if (!s) return 0;
    if (wcsstr(s, L"Localization") || wcsstr(s, L"localization")) return 1;
    if (wcsstr(s, L"locres")) return 1;
    if (wcsstr(s, L"Paks") || wcsstr(s, L".pak")) return 1;   /* 诊断：pak 目录也记，用来确认 hook 真的生效 */
    return 0;
}

static void log_enum(const wchar_t* kind, LPCWSTR pattern, HANDLE h) {
    if (!g_logFiles || !want_dir_log(pattern)) return;
    wchar_t line[1200];
    lstrcpynW(line, (h == INVALID_HANDLE_VALUE) ? L"enum-miss " : L"enum-hit  ", 12);
    lstrcatW(line, kind);
    lstrcatW(line, L" ");
    lstrcpynW(line + lstrlenW(line), pattern ? pattern : L"(null)", 900);
    logw(line);
}

static HANDLE WINAPI Hooked_FindFirstFileW(LPCWSTR pattern, LPWIN32_FIND_DATAW fd) {
    if (!g_realFFF) return INVALID_HANDLE_VALUE;
    HANDLE h = g_realFFF(pattern, fd);
    log_enum(L"FFF", pattern, h);
    return h;
}

static HANDLE WINAPI Hooked_FindFirstFileExW(LPCWSTR pattern, int level, LPWIN32_FIND_DATAW fd,
                                             int searchOp, DWORD flags) {
    if (!g_realFFFE) return INVALID_HANDLE_VALUE;
    HANDLE h = g_realFFFE(pattern, level, fd, searchOp, flags);
    log_enum(L"FFFE", pattern, h);
    return h;
}

static void patch_iat(void) {
    HMODULE k32 = GetModuleHandleW(L"kernel32.dll");
    if (!k32) return;
    FARPROC target = GetProcAddress(k32, "GetCommandLineW");
    if (!target) return;
    BYTE* base = (BYTE*)GetModuleHandleW(NULL);
    if (!base) return;
    IMAGE_DOS_HEADER* dos = (IMAGE_DOS_HEADER*)base;
    IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(base + dos->e_lfanew);
    IMAGE_DATA_DIRECTORY dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!dir.VirtualAddress) return;
    int patched = 0;
    IMAGE_IMPORT_DESCRIPTOR* imp = (IMAGE_IMPORT_DESCRIPTOR*)(base + dir.VirtualAddress);
    for (; imp->Name; ++imp) {
        IMAGE_THUNK_DATA* thunk = (IMAGE_THUNK_DATA*)(base + imp->FirstThunk);
        for (; thunk->u1.Function; ++thunk) {
            FARPROC* slot = (FARPROC*)&thunk->u1.Function;
            if (*slot != target) continue;
            DWORD old = 0;
            if (VirtualProtect(slot, sizeof(void*), PAGE_READWRITE, &old)) {
                *slot = (FARPROC)&Hooked_GetCommandLineW;
                VirtualProtect(slot, sizeof(void*), old, &old);
                ++patched;
            }
        }
    }
    if (g_logFiles && g_realCFW) {
        FARPROC cfw = GetProcAddress(k32, "CreateFileW");
        if (cfw) {
            IMAGE_IMPORT_DESCRIPTOR* d2 = (IMAGE_IMPORT_DESCRIPTOR*)(base + dir.VirtualAddress);
            for (; d2->Name; ++d2) {
                IMAGE_THUNK_DATA* t2 = (IMAGE_THUNK_DATA*)(base + d2->FirstThunk);
                for (; t2->u1.Function; ++t2) {
                    FARPROC* slot2 = (FARPROC*)&t2->u1.Function;
                    if (*slot2 != cfw) continue;
                    DWORD old2 = 0;
                    if (VirtualProtect(slot2, sizeof(void*), PAGE_READWRITE, &old2)) {
                        *slot2 = (FARPROC)&Hooked_CreateFileW;
                        VirtualProtect(slot2, sizeof(void*), old2, &old2);
                    }
                }
            }
        }
    }
    if (g_logFiles) {
        FARPROC fff  = GetProcAddress(k32, "FindFirstFileW");
        FARPROC fffe = GetProcAddress(k32, "FindFirstFileExW");
        IMAGE_IMPORT_DESCRIPTOR* d3 = (IMAGE_IMPORT_DESCRIPTOR*)(base + dir.VirtualAddress);
        for (; d3->Name; ++d3) {
            IMAGE_THUNK_DATA* t3 = (IMAGE_THUNK_DATA*)(base + d3->FirstThunk);
            for (; t3->u1.Function; ++t3) {
                FARPROC* slot3 = (FARPROC*)&t3->u1.Function;
                FARPROC repl = NULL;
                if (fff && *slot3 == fff) repl = (FARPROC)&Hooked_FindFirstFileW;
                else if (fffe && *slot3 == fffe) repl = (FARPROC)&Hooked_FindFirstFileExW;
                if (!repl) continue;
                DWORD old3 = 0;
                if (VirtualProtect(slot3, sizeof(void*), PAGE_READWRITE, &old3)) {
                    *slot3 = repl;
                    VirtualProtect(slot3, sizeof(void*), old3, &old3);
                }
            }
        }
    }
    char msg[300];
    lstrcpyA(msg, "[");
    WideCharToMultiByte(CP_ACP, 0, HOST, -1, msg + lstrlenA(msg), 64, 0, 0);
    lstrcatA(msg, "] GetCommandLineW hooked slots=");
    char num[16];
    int v = patched, j = 0;
    char tmp[16];
    int k = 0;
    if (v == 0) { tmp[k++] = '0'; }
    while (v > 0) { tmp[k++] = (char)('0' + (v % 10)); v /= 10; }
    while (k > 0) { num[j++] = tmp[--k]; }
    num[j] = 0;
    lstrcatA(msg, num);
    lstrcatA(msg, " arg=");
    WideCharToMultiByte(CP_ACP, 0, ARG, -1, msg + lstrlenA(msg), 128, 0, 0);
    logline(msg);
}

__PATCH_CODE__

BOOL WINAPI DllMain(HINSTANCE hInst, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hInst);
        g_real = LoadLibraryW(REALD);
        if (g_real) {
__DERIVED_RESOLVE__
        }
        HMODULE k32 = GetModuleHandleW(L"kernel32.dll");
        if (k32) g_realGCL = (LPWSTR (WINAPI *)(void))GetProcAddress(k32, "GetCommandLineW");
        if (k32) g_realCFW = (HANDLE (WINAPI *)(LPCWSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES,
                                                DWORD, DWORD, HANDLE))GetProcAddress(k32, "CreateFileW");
        if (k32) g_realFFF  = (FN_FFF)GetProcAddress(k32, "FindFirstFileW");
        if (k32) g_realFFFE = (FN_FFFE)GetProcAddress(k32, "FindFirstFileExW");
        if (g_realGCL) patch_iat();
        __PATCH_CALL__
    }
    return TRUE;
}
'''

ASM_HEAD = "option casemap:none\n\n"
ASM_END = "end\n"


def _hijackable_imports(exe):
    """返回可作为宿主的导入 DLL 列表（跳过 ApiSet / 系统关键 DLL / 不存在的）。"""
    try:
        pe = PE(exe)
    except Exception:
        return []
    out = []
    for name in pe.imports():
        low = name.lower()
        if low.startswith("api-ms-win-") or low in BAD_HOSTS:
            continue
        sys_path = os.path.join(SYSTEM32, name)
        if not os.path.isfile(sys_path):
            continue
        try:
            if len(PE(sys_path).exports()) <= 0:
                continue
        except Exception:
            continue
        out.append(name)
    return out


def _find_real_exe(exe):
    """给的若是启动器/包装 exe，往下找真正的 *Shipping.exe。"""
    root = os.path.dirname(os.path.abspath(exe))
    hits = []
    for cur, dirs, files in os.walk(root):
        if cur.count(os.sep) - root.count(os.sep) >= 5:
            dirs[:] = []
        for f in files:
            if f.lower().endswith(".exe") and "shipping" in f.lower():
                hits.append(os.path.join(cur, f))
    if not hits:
        return None
    hits.sort(key=lambda c: (-os.path.getsize(c), len(c)))
    return hits[0]


def resolve_exe(path):
    """把用户给的路径统一成一个 exe 绝对路径。

    支持：
      1) 直接给 exe 文件
      2) 给 exe 所在目录
      3) 给游戏根目录 —— 在 4 层以内找 *Shipping.exe，找不到就找同层最大的 exe
    """
    p = os.path.abspath(path.strip().strip('"'))
    if os.path.isfile(p):
        if _hijackable_imports(p):
            return p
        real = _find_real_exe(p)
        if real and _hijackable_imports(real):
            print("注意：%s 没有可劫持的导入 DLL（这是启动器/包装 exe），自动改用真正的游戏本体：" % os.path.basename(p))
            print("      -> %s" % real)
            return real
        return p
    if not os.path.isdir(p):
        sys.exit("路径不存在: %s" % p)
    base_depth = p.rstrip("\\").count("\\")
    all_exes, shippings = [], []
    for cur, dirs, files in os.walk(p):
        if cur.count("\\") - base_depth >= 4:
            dirs[:] = []
        for f in files:
            if f.lower().endswith(".exe"):
                full = os.path.join(cur, f)
                all_exes.append(full)
                if "shipping" in f.lower():
                    shippings.append(full)
    if shippings:
        pool = shippings
    else:
        pool = all_exes
    if not pool:
        sys.exit("在 %s 下没找到 exe（可以直接把 exe 拖给本工具）" % p)
    if len(pool) > 1:
        pool.sort(key=lambda c: (-os.path.getsize(c), len(c)))
        print("发现 %d 个候选 exe，自动选最像游戏本体的那个：" % len(pool))
        for c in pool[:5]:
            print("  - %s" % c)
    chosen = pool[0]
    if not _hijackable_imports(chosen):
        real = _find_real_exe(chosen)
        if real and _hijackable_imports(real):
            print("注意：%s 没有可劫持的导入 DLL，自动改用 %s" % (os.path.basename(chosen), real))
            chosen = real
    return chosen


def pick_host(exe, prefer=None):
    """按导入表自动挑宿主 DLL：导出数最少、且不是系统关键 DLL。"""
    pe = PE(exe)
    exe_dir = os.path.dirname(exe)
    ordi = pe.ordinal_imports()
    scored = []
    skipped_ordinal = []
    for name in pe.imports():
        low = name.lower()
        if low.startswith("api-ms-win-") or low in BAD_HOSTS:
            continue
        if prefer and prefer.lower().rstrip(".dll") in low:
            if name in ordi:
                sys.stderr.write("警告：%s 有按序号导入 %s，纯名字式代理很可能加载失败；已按你的要求使用。\n"
                                 % (name, ordi[name]))
            return name
        if name in ordi:
            skipped_ordinal.append((name, ordi[name]))
            continue
        sys_path = os.path.join(SYSTEM32, name)
        if not os.path.isfile(sys_path):
            continue
        try:
            exp = len(PE(sys_path).exports())
        except Exception:
            continue
        if exp <= 0:
            continue
        in_dir = os.path.isfile(os.path.join(exe_dir, name))
        risky = 1 if low in RISKY_HOSTS else 0
        scored.append((risky, exp, in_dir, name))
    if not scored:
        if skipped_ordinal:
            sys.stderr.write("以下 DLL 因【按序号导入】被排除（做代理会加载失败）：%s\n"
                             % ", ".join("%s(序号 %s)" % (n, v) for n, v in skipped_ordinal))
        sys.exit("这个 exe 没有可劫持的导入 DLL（可能全走 ApiSet，或静态链接）。\n"
                 "如果它是启动器/包装 exe，请改指向真正的游戏本体，例如 ...\\Binaries\\Win64\\<游戏>-Win64-Shipping.exe")
    scored.sort()
    return scored[0][3]


def cmd_list(args):
    args.exe = resolve_exe(args.exe)
    pe = PE(args.exe)
    exe_dir = os.path.dirname(os.path.abspath(args.exe))
    print("目标 exe : %s" % args.exe)
    print("架构     : x64\n")
    print("%-30s %-8s %-10s %s" % ("导入的 DLL", "导出数", "同目录有", "评价"))
    print("-" * 76)
    stars = []
    for name in pe.imports():
        low = name.lower()
        sys_path = os.path.join(SYSTEM32, name)
        exp = None
        if os.path.isfile(sys_path):
            try:
                exp = len(PE(sys_path).exports())
            except Exception:
                exp = None
        in_dir = os.path.isfile(os.path.join(exe_dir, name))
        if low.startswith("api-ms-win-"):
            verdict = "跳过（ApiSet 虚拟名，本地文件不生效）"
        elif low in BAD_HOSTS:
            verdict = "不建议（系统关键/易冲突）"
        elif exp is None:
            verdict = "跳过（找不到系统副本）"
        elif exp == 0:
            verdict = "跳过（没有导出，转发不了）"
        elif exp <= 20:
            verdict = "★ 首选（导出少）"
            stars.append(name)
        elif exp <= 200:
            verdict = "可用"
        else:
            verdict = "可用但导出多"
        print("%-30s %-8s %-10s %s" % (name, "-" if exp is None else exp,
                                       "是" if in_dir else "-", verdict))
    print()
    print("建议宿主：%s" % (", ".join(stars) if stars else "（没有明显首选，从“可用”里挑导出少的）"))


def _is_ours(path):
    """目标文件是不是本工具产物（二进制里带 raosig 标记）。"""
    try:
        blob = open(path, "rb").read()
    except Exception:
        return False
    return (b"raosig" in blob) or ("raosig".encode("utf-16-le") in blob)


def _cleanup_after_deploy(exe_dir, host, work, keep=False):
    """部署后收尾：删掉同目录里旧的代理 DLL，删掉本次临时编译目录。"""
    removed = []
    try:
        for name in sorted(os.listdir(exe_dir)):
            if not name.lower().endswith(".dll") or name.lower() == host.lower():
                continue
            full = os.path.join(exe_dir, name)
            if os.path.isfile(full) and _is_ours(full):
                os.remove(full)
                removed.append(name)
                lg = full + ".raosig.log"
                if os.path.isfile(lg):
                    os.remove(lg)
    except Exception:
        pass
    if removed:
        print("已清理旧代理: %s" % ", ".join(removed))
    if keep:
        print("保留临时目录（--keep-work）: %s" % work)
        return
    try:
        shutil.rmtree(work, ignore_errors=True)
        if not os.path.isdir(work):
            print("已清理临时目录: %s" % work)
    except Exception:
        pass


def cmd_clean(args):
    """清理历史残留：临时编译目录 + 可选地删掉某游戏目录里已部署的代理 DLL。"""
    tmp = tempfile.gettempdir()
    dirs, freed = 0, 0
    for name in sorted(os.listdir(tmp)):
        if not name.startswith("raosig_"):
            continue
        full = os.path.join(tmp, name)
        if not os.path.isdir(full):
            continue
        sz = 0
        for r, _, fs in os.walk(full):
            for f in fs:
                try:
                    sz += os.path.getsize(os.path.join(r, f))
                except Exception:
                    pass
        shutil.rmtree(full, ignore_errors=True)
        if not os.path.isdir(full):
            dirs += 1
            freed += sz
            print("已删除临时目录: %s" % full)
    dlls = 0
    if getattr(args, "exe", None):
        exe_dir = os.path.dirname(os.path.abspath(resolve_exe(args.exe)))
        for name in sorted(os.listdir(exe_dir)):
            if not name.lower().endswith(".dll"):
                continue
            full = os.path.join(exe_dir, name)
            if os.path.isfile(full) and _is_ours(full):
                os.remove(full)
                dlls += 1
                print("已删除代理 DLL: %s" % full)
                lg = full + ".raosig.log"
                if os.path.isfile(lg):
                    os.remove(lg)
    print("清理完成：临时目录 %d 个（释放 %.1f KB），代理 DLL %d 个" % (dirs, freed / 1024.0, dlls))


def cmd_build(args):
    host = args.host
    if not host.lower().endswith(".dll"):
        host += ".dll"
    exe = os.path.abspath(args.exe)
    exe_dir = os.path.dirname(exe)
    real_sys = os.path.join(SYSTEM32, host)
    if not os.path.isfile(real_sys):
        sys.exit("找不到系统 DLL: %s" % real_sys)

    exports = PE(real_sys).exports()
    named = [(o, n) for (o, n) in exports if n]
    if not named:
        sys.exit("%s 没有可转发的具名导出" % host)

    work = args.work or os.path.join(tempfile.gettempdir(), "raosig_" + host.replace(".", "_"))
    os.makedirs(work, exist_ok=True)

    # ---- 生成 .asm：每个导出一条 jmp [p_stubN]
    asm = [ASM_HEAD]
    for i, (o, n) in enumerate(named):
        asm.append("extern p_stub%d:QWORD\n" % i)
    asm.append("\n.code\n")
    for i, (o, n) in enumerate(named):
        asm.append("stub%d proc\n    jmp qword ptr [p_stub%d]\nstub%d endp\n" % (i, i, i))
    asm.append(ASM_END)
    open(os.path.join(work, "proxy.asm"), "w", encoding="ascii", newline="\r\n").write("".join(asm))

    # ---- 生成 .def：原名导出到 stubN
    defs = ["LIBRARY %s\nEXPORTS\n" % host[:-4]]
    for i, (o, n) in enumerate(named):
        defs.append("    %s=stub%d @%d\n" % (n, i, o))
    open(os.path.join(work, "proxy.def"), "w", encoding="ascii", newline="\r\n").write("".join(defs))

    # ---- 生成 .cpp
    ptrs = "\n".join('extern "C" void* p_stub%d = 0;' % i for i in range(len(named)))
    resolve = "\n".join('            p_stub%d = (void*)GetProcAddress(g_real, "%s");'
                        % (i, n.replace('"', '')) for i, (o, n) in enumerate(named))
    # ---- 代码补丁（--patch RVA:HEX，可重复）
    parsed = []
    for spec in (getattr(args, "patch", None) or []):
        try:
            rva_s, hex_s = spec.split(":", 1)
            rva = int(rva_s, 16)
            data = bytes.fromhex(hex_s.replace(" ", "").replace("0x", ""))
            if not data:
                raise ValueError
        except Exception:
            sys.exit("--patch 格式应为 RVA:HEX，例如 --patch 0x19F2C7F:EB04")
        parsed.append((rva, data))
    if parsed:
        plines = []
        for i, (rva, data) in enumerate(parsed):
            plines.append("static const BYTE g_patch%d[] = { %s };"
                          % (i, ", ".join("0x%02X" % b for b in data)))
        plines.append("typedef struct { DWORD rva; int len; const BYTE* data; } RAOSIG_PATCH;")
        plines.append("static const RAOSIG_PATCH g_patches[] = { %s };"
                      % ", ".join("{ 0x%X, %d, g_patch%d }" % (rva, len(data), i)
                                  for i, (rva, data) in enumerate(parsed)))
        plines.append("""
static void raosig_hex(char* out, unsigned int v) {
    char tmp[16]; int k = 0, j = 0;
    if (v == 0) { out[j++] = '0'; }
    while (v > 0) { int d = (int)(v % 16); tmp[k++] = (char)(d < 10 ? '0' + d : 'A' + d - 10); v /= 16; }
    while (k > 0) out[j++] = tmp[--k];
    out[j] = 0;
}

static void apply_patches(void) {
    BYTE* base = (BYTE*)GetModuleHandleW(NULL);
    if (!base) return;
    int n = (int)(sizeof(g_patches) / sizeof(g_patches[0]));
    for (int i = 0; i < n; ++i) {
        BYTE* addr = base + g_patches[i].rva;
        DWORD old = 0;
        if (!VirtualProtect(addr, (SIZE_T)g_patches[i].len, PAGE_EXECUTE_READWRITE, &old)) continue;
        CopyMemory(addr, g_patches[i].data, (SIZE_T)g_patches[i].len);
        VirtualProtect(addr, (SIZE_T)g_patches[i].len, old, &old);
        FlushInstructionCache(GetCurrentProcess(), addr, (SIZE_T)g_patches[i].len);
        if (g_logFiles) {
            char m[128]; char hx[24];
            lstrcpyA(m, "[");
            WideCharToMultiByte(CP_ACP, 0, HOST, -1, m + lstrlenA(m), 64, 0, 0);
            lstrcatA(m, "] patch rva=0x");
            raosig_hex(hx, g_patches[i].rva);
            lstrcatA(m, hx);
            lstrcatA(m, " ok");
            logline(m);
        }
    }
}""")
        patch_code = "\n".join(plines)
        patch_call = "apply_patches();"
        print("代码补丁 : %d 处 %s" % (len(parsed), ", ".join("0x%X" % r for r, _ in parsed)))
    else:
        patch_code, patch_call = "", ""

    cpp = (CPP_TEMPLATE
           .replace("__ARG__", args.arg)
           .replace("__HOST__", host)
           .replace("__REALDLL__", real_sys.replace("\\", "\\\\"))
           .replace("__LOGNAME__", host + ".raosig.log")
           .replace("__LOGFILES__", "1" if getattr(args, "log_files", False) else "0")
           .replace("__PATCH_CODE__", patch_code)
           .replace("__PATCH_CALL__", patch_call)
           .replace("__DERIVED_POINTERS__", ptrs)
           .replace("__DERIVED_RESOLVE__", resolve))
    open(os.path.join(work, "proxy.cpp"), "w", encoding="utf-8", newline="\r\n").write(cpp)

    vcvars = find_vcvars()
    if not vcvars:
        sys.exit("找不到 vcvars64.bat（需要 VS2022 的“使用 C++ 的桌面开发”）。详见 README。")
    print("编译器 : %s" % vcvars)

    out_dll = os.path.join(work, host)
    for f in ("proxy.obj", "proxyasm.obj", host):
        p = os.path.join(work, f)
        if os.path.isfile(p):
            os.remove(p)
    bat = (
        "@echo off\r\n"
        'call "{vc}" >nul 2>&1 || (echo [ERR] vcvars failed & exit /b 2)\r\n'
        "cd /d \"%~dp0\"\r\n"
        "cl /nologo /c /GS- /EHsc /utf-8 proxy.cpp\r\n"
        "if errorlevel 1 exit /b 3\r\n"
        "ml64 /nologo /c /Fo proxyasm.obj proxy.asm\r\n"
        "if errorlevel 1 exit /b 4\r\n"
        'link /nologo /DLL /DEF:proxy.def /OUT:"{host}" proxy.obj proxyasm.obj\r\n'
        "exit /b %errorlevel%\r\n"
    ).format(vc=vcvars, host=host)
    bat_path = os.path.join(work, "build.bat")
    open(bat_path, "w", encoding="mbcs", newline="").write(bat)
    p = subprocess.run(["cmd", "/c", bat_path], cwd=work,
                       capture_output=True, text=True, errors="replace")
    if p.returncode != 0 or not os.path.isfile(out_dll):
        print(p.stdout[-3000:])
        print(p.stderr[-3000:])
        sys.exit("编译失败 (exit=%s)" % p.returncode)
    print("编译输出: %s (%d B)" % (out_dll, os.path.getsize(out_dll)))

    # ---- 校验
    got = PE(out_dll).exports()
    want = set(n for _, n in named)
    have = set(n for _, n in got if n)
    missing, extra = want - have, have - want
    print("导出校验: 目标 %d / 代理 %d / 缺 %d / 多 %d" % (len(want), len(have), len(missing), len(extra)))
    if missing:
        print("  缺少: %s" % ", ".join(sorted(missing))[:400])
    if missing or extra:
        sys.exit("导出表不一致，拒绝部署")
    dep = PE(out_dll).imports()
    deps = [d for d in dep if d]
    print("依赖: %s" % (", ".join(deps) or "?"))
    bad = [d for d in deps if d.lower() not in
           ("kernel32.dll", "kernelbase.dll", "msvcrt.dll", "ucrtbase.dll",
            "vcruntime140.dll", "vcruntime140_1.dll", "api-ms-win-crt-runtime-l1-1-0.dll",
            "api-ms-win-crt-stdio-l1-1-0.dll", "api-ms-win-crt-heap-l1-1-0.dll",
            "api-ms-win-crt-string-l1-1-0.dll", "api-ms-win-crt-convert-l1-1-0.dll",
            "api-ms-win-crt-math-l1-1-0.dll", "api-ms-win-crt-locale-l1-1-0.dll",
            "api-ms-win-crt-filesystem-l1-1-0.dll", "api-ms-win-crt-environment-l1-1-0.dll",
            "api-ms-win-crt-utility-l1-1-0.dll", "api-ms-win-crt-multibyte-l1-1-0.dll",
            "api-ms-win-crt-conio-l1-1-0.dll", "api-ms-win-crt-time-l1-1-0.dll",
            "api-ms-win-crt-process-l1-1-0.dll", "api-ms-win-crt-private-l1-1-0.dll")]
    if bad:
        print("  注意：额外依赖 %s（通常也能跑）" % ", ".join(bad))

    if not args.deploy:
        print("\n未部署（加 --deploy 才会拷进游戏目录）。生成物: %s" % work)
        return

    tgt = os.path.join(exe_dir, host)
    bak = tgt + ".raosig-bak"
    already_ours = False
    if os.path.isfile(tgt):
        already_ours = _is_ours(tgt)
    if os.path.isfile(tgt) and not already_ours and not os.path.isfile(bak):
        shutil.copy2(tgt, bak)
        print("已备份原 %s -> %s" % (host, os.path.basename(bak)))
    elif already_ours:
        print("目标位置已是本工具产物，跳过备份")
    if os.path.isfile(tgt):
        os.remove(tgt)
    shutil.copy2(out_dll, tgt)
    print("已部署: %s" % tgt)
    _write_note(exe_dir, host, args)
    _cleanup_after_deploy(exe_dir, host, work, keep=getattr(args, "keep_work", False))


def _note_text(host, args):
    """给生成的代理 DLL 配一份英文说明（同目录、同主名 .txt）。"""
    arg = getattr(args, "arg", "") or ""
    patches = list(getattr(args, "patch", None) or [])
    log_name = "%TEMP%\\" + host + ".raosig.log"
    regen = 'python raosig.py auto --exe "<game root>"'
    if arg:
        regen += " --arg=" + arg
    for p in patches:
        regen += " --patch " + p

    lines = [
        "%s  --  PAK SIGNATURE BYPASS PROXY DLL" % host,
        "Generated by raosig on %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "",
        "WHAT THIS FILE IS",
        "  This is NOT the genuine Windows %s." % host,
        "  The real DLL is still loaded from C:\\Windows\\System32\\%s at run time." % host,
        "  This file only exists so the game loads it first and gets patched.",
        "",
        "WHAT IT DOES",
        "  1. Proxy: every exported function is forwarded to the genuine system DLL,",
        "     so the game keeps working exactly as before.",
        "  2. Hooks KERNEL32!GetCommandLineW so the process sees an extra command",
        "     line switch (added in memory; the shortcut is not modified).",
    ]
    if arg:
        lines.append("     extra switch : %s" % arg)
    lines.append("  3. Applies in-memory code patches that skip the pak signature check.")
    if patches:
        lines.append("     patches      : %s" % ", ".join(patches))
    lines += [
        "",
        "WHY THIS IS NEEDED",
        "  The game requires a matching .sig file next to every .pak it mounts.",
        "  Unsigned mod paks are silently dropped. With the patch above, unsigned",
        "  paks mount normally and mods / translations placed in Paks start working.",
        "",
        "HOW TO DISABLE",
        "  Rename or delete this DLL (for example %s.off)." % host,
        "  The game then loads the system DLL again and the original signature",
        "  check comes back.",
        "",
        "LOG",
        "  " + log_name,
        "",
        "HOW TO REGENERATE",
        "  " + regen,
        "",
    ]
    return "\r\n".join(lines)


def _write_note(exe_dir, host, args):
    note = os.path.join(exe_dir, os.path.splitext(host)[0] + ".txt")
    try:
        with io.open(note, "w", encoding="utf-8", newline="") as f:
            f.write(_note_text(host, args))
        print("已写说明: %s" % note)
    except Exception as exc:  # noqa: BLE001
        print("写说明失败（不影响 DLL）: %s" % exc)


def cmd_uninstall(args):
    host = args.host
    if not host.lower().endswith(".dll"):
        host += ".dll"
    exe_dir = os.path.dirname(os.path.abspath(args.exe))
    tgt = os.path.join(exe_dir, host)
    bak = tgt + ".raosig-bak"
    if os.path.isfile(tgt):
        os.remove(tgt)
    if os.path.isfile(bak):
        shutil.move(bak, tgt)
        print("已还原备份: %s" % tgt)
    log = os.path.join(exe_dir, host + ".raosig.log")
    if os.path.isfile(log):
        os.remove(log)
    note = os.path.join(exe_dir, os.path.splitext(host)[0] + ".txt")
    if os.path.isfile(note):
        os.remove(note)
    print("已卸载 %s" % host)


class _A(object):
    """给 cmd_build 用的简易参数对象。"""
    pass


def cmd_auto(args):
    exe = resolve_exe(args.exe)
    host = args.host or pick_host(exe)
    print("目标 exe : %s" % exe)
    print("自动宿主 : %s" % host)
    print("注入参数 : %s\n" % args.arg)
    a = _A()
    a.exe = exe
    a.host = host
    a.arg = args.arg
    a.deploy = True
    a.work = args.work
    a.log_files = getattr(args, "log_files", False)
    a.keep_work = getattr(args, "keep_work", False)
    a.patch = getattr(args, "patch", None)
    cmd_build(a)


def _walk_exes(root, depth):
    root = os.path.abspath(root)
    base_depth = root.rstrip("\\").count("\\")
    hits = []
    for cur, dirs, files in os.walk(root):
        if cur.count("\\") - base_depth >= depth:
            dirs[:] = []
        for f in files:
            if f.lower().endswith(".exe"):
                hits.append(os.path.join(cur, f))
    return hits


def cmd_scan(args):
    all_exes = _walk_exes(args.root, args.depth)
    cands = [e for e in all_exes if "shipping" in os.path.basename(e).lower()]
    if not cands:
        cands = all_exes
    if not cands:
        sys.exit("在 %s 下没找到 exe" % args.root)
    print("找到 %d 个候选 exe（深度 %d）\n" % (len(cands), args.depth))
    print("%-58s %s" % ("exe", "推荐宿主"))
    print("-" * 90)
    plan = []
    for e in sorted(cands):
        try:
            pe = PE(e)
            if pe.machine != 0x8664:
                print("%-58s 跳过（非 x64）" % (os.path.basename(e)))
                continue
            host = pick_host(e)
        except SystemExit:
            print("%-58s 跳过（无可劫持导入）" % (os.path.basename(e)))
            continue
        except Exception as ex:
            print("%-58s 跳过（%s）" % (os.path.basename(e), ex))
            continue
        short = e if len(e) <= 58 else "..." + e[-55:]
        print("%-58s %s" % (short, host))
        plan.append((e, host))
    print()
    if not args.apply:
        print("只扫描不动作。加 --apply 就对上面每个游戏编译+部署。")
        return
    for e, host in plan:
        print("\n==== %s ====" % e)
        a = _A()
        a.exe = e
        a.host = host
        a.arg = args.arg
        a.deploy = True
        a.work = None
        a.log_files = False
        a.keep_work = False
        a.patch = getattr(args, "patch", None)
        try:
            cmd_build(a)
        except SystemExit as ex:
            print("  失败: %s" % ex)


def main():
    ap = argparse.ArgumentParser(prog="raosig", description="绕sig补丁生成器：给 UE 游戏自动注入命令行参数")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("list", help="列出可劫持的 DLL")
    p1.add_argument("--exe", required=True, help="exe 文件，或游戏目录（自动找）")
    p1.set_defaults(func=cmd_list)

    p2 = sub.add_parser("build", help="生成并编译代理 DLL")
    p2.add_argument("--exe", required=True, help="exe 文件，或游戏目录（自动找）")
    p2.add_argument("--host", required=True, help="宿主 DLL 名，如 XAPOFX1_5")
    p2.add_argument("--arg", required=True, help='注入的参数，Windows 上请写成 --arg=-fileopenlog')
    p2.add_argument("--deploy", action="store_true", help="校验通过后直接部署到 exe 目录")
    p2.add_argument("--work", help="工作目录")
    p2.add_argument("--keep-work", action="store_true", help="部署后保留临时编译目录（默认删掉）")
    p2.add_argument("--log-files", action="store_true", help="记录引擎打开了哪些 .pak/.sig/.locres（写到 %TEMP%\\<宿主>.raosig.log）")
    p2.add_argument("--patch", action="append", metavar="RVA:HEX",
                    help="启动时打代码补丁，可重复，例：--patch 0x19F2C7F:EB04")
    p2.set_defaults(func=cmd_build)

    p3 = sub.add_parser("uninstall", help="卸载并还原")
    p3.add_argument("--exe", required=True, help="exe 文件，或游戏目录")
    p3.add_argument("--host", required=True)
    p3.set_defaults(func=cmd_uninstall)

    p4 = sub.add_parser("auto", help="一条命令搞定：自动选宿主 + 编译 + 部署")
    p4.add_argument("--exe", required=True, help="exe 文件，或游戏目录（自动找）")
    p4.add_argument("--arg", default="-fileopenlog", help="要注入的参数，默认 -fileopenlog")
    p4.add_argument("--host", help="手动指定宿主（不给就自动挑导出最少的）")
    p4.add_argument("--deploy", action="store_true", help="（默认就会部署，加不加都一样）")
    p4.add_argument("--work", help="工作目录")
    p4.add_argument("--keep-work", action="store_true", help="部署后保留临时编译目录（默认删掉）")
    p4.add_argument("--log-files", action="store_true", help="记录引擎打开了哪些 .pak/.sig/.locres（写到 %TEMP%\\<宿主>.raosig.log）")
    p4.add_argument("--patch", action="append", metavar="RVA:HEX",
                    help="启动时打代码补丁，可重复，例：--patch 0x19F2C7F:EB04")
    p4.set_defaults(func=cmd_auto)

    p6 = sub.add_parser("clean", help="清理历史残留：临时编译目录 + 可选的代理 DLL")
    p6.add_argument("--exe", help="顺手删掉这个游戏目录里本工具部署过的代理 DLL")
    p6.set_defaults(func=cmd_clean)

    p5 = sub.add_parser("scan", help="扫一个目录下所有 UE 游戏，列出推荐宿主")
    p5.add_argument("--root", required=True, help="游戏根目录，如 D:\\Games")
    p5.add_argument("--depth", type=int, default=4, help="搜索深度，默认 4")
    p5.add_argument("--arg", default="-fileopenlog")
    p5.add_argument("--apply", action="store_true", help="对每个游戏直接编译并部署")
    p5.add_argument("--patch", action="append", metavar="RVA:HEX", help="同 build 的 --patch")
    p5.set_defaults(func=cmd_scan)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
