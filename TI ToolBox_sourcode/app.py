#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TI工具箱 - 本地后端

设计原则：**工具全部写在 catalog.json 里**。
新增一个工具 = 往 catalog.json 加一个 module（含 tasks 的 cmd 模板），
后端只负责把模板里的占位符换成真实路径、起进程、把输出回传前端。
以后接 GitHub 仓库，就是让远端下发同样结构的 catalog 条目。
"""
from __future__ import annotations

import csv
import json
import os
import tempfile
import shutil
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import urllib.request
import urllib.error

if getattr(sys, "frozen", False):
    HERE = Path(sys.executable).resolve().parent   # exe 同目录（用户可写的落盘位置）
else:
    HERE = Path(__file__).resolve().parent
BUNDLE = Path(getattr(sys, "_MEIPASS", HERE))
UI = BUNDLE / "ui"
# 外置清单优先：用户/GitHub 下发的 catalog.json 放在 exe 旁边即可热更新工具列表
CATALOG = HERE / "catalog.json"
if not CATALOG.exists():
    CATALOG = BUNDLE / "catalog.json"

TARGET_JSON = HERE / "target.json"          # 用户改的目标，写在 exe 旁边
SETTINGS_JSON = HERE / "settings.json"      # 用户改的路径（工具目录 / node），写在 exe 旁边
AESKEY_NAME = "AESKEY.txt"

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
JOBS: dict[str, dict] = {}
LOCK = threading.Lock()


# ---------------------------------------------------------------- 基础
def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def catalog() -> dict:
    return read_json(CATALOG, {"modules": [], "vars": {}})


def tool_dir() -> Path:
    # 走 _vars() 才能展开 {app} 这类嵌套占位符
    return Path(_vars().get("tool", ""))


def python_exe():
    """内置/系统 python：settings → 本机 DSH 运行时 → PATH → python。"""
    st = read_json(SETTINGS_JSON, {})
    cand = []
    if st.get("py"):
        cand.append(st["py"])
    local = HERE / "tools" / "python" / "python.exe"
    cand.append(str(local))
    cand.append(os.path.expanduser(r"~\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"))
    cand += [shutil.which("python"), shutil.which("python3")]
    for c in cand:
        if c and Path(c).exists():
            return c
    return "python"


def node_exe() -> str:
    cand = (read_json(SETTINGS_JSON, {}) or {}).get("node") or catalog().get("vars", {}).get("node", "")
    if cand:
        cand = cand.replace("{app}", str(HERE))
        if Path(cand).exists():
            return cand
    # 内置优先：tools\node\node.exe（将来把便携 node 塞进来就能全自带）
    for p in (HERE / "tools" / "node" / "node.exe",
              Path(r"C:\Program Files\nodejs\node.exe"),
              Path(r"C:\Program Files (x86)\nodejs\node.exe")):
        if Path(p).exists():
            return str(p)
    return "node"


def game_name(path: str) -> str:
    """从 key 的落盘路径猜游戏名：优先取 Content/Binaries 的上一级，否则用所在目录名。"""
    if not path:
        return ""
    parts = [x for x in re.split(r"[\\/]+", path) if x]
    for i, seg in enumerate(parts[:-1]):
        if parts[i + 1].lower() in ("content", "binaries"):
            return seg
    for seg in reversed(parts[:-1]):
        if seg.lower() not in ("content", "paks", "win64", "binaries"):
            return seg
    return ""



# ---------------------------------------------------------------- 窗口控制（Win32）
_WIN_TITLE = "TI工具箱"
_drag = {"cur": None, "rect": None}


def _hwnd():
    """本进程（pywebview 同进程）最大的可见顶层窗口句柄。"""
    import ctypes
    from ctypes import wintypes

    if sys.platform != "win32":
        return 0
    u = ctypes.windll.user32
    pid = os.getpid()
    best = {"h": 0, "area": 0}
    CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    class RECT(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                    ("r", ctypes.c_long), ("b", ctypes.c_long)]

    def _cb(h, _lp):
        wpid = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(wpid))
        if wpid.value != pid or not u.IsWindowVisible(h):
            return True
        rc = RECT()
        u.GetWindowRect(h, ctypes.byref(rc))
        area = max(0, rc.r - rc.l) * max(0, rc.b - rc.t)
        if area > best["area"]:
            best["h"], best["area"] = h, area
        return True

    u.EnumWindows(CB(_cb), 0)
    return best["h"]


def pick_dir(timeout: int = 300):
    """弹系统「选择文件夹」对话框，返回路径（取消则空串）。"""
    import subprocess
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms | Out-Null; "
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$d.Description = '选择游戏根目录（含 Content / Binaries 的那一层）'; "
        "$d.ShowNewFolderButton = $true; "
        "if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { "
        "[Console]::Out.Write($d.SelectedPath) }"
    )
    flags = 0x08000000 if sys.platform == "win32" else 0
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", ps],
            capture_output=True, timeout=timeout, creationflags=flags,
        )
        return r.stdout.decode("utf-8", "ignore").strip()
    except Exception:
        return ""


def pick_file(filter_desc: str = "可执行文件 (*.exe)|*.exe|所有文件 (*.*)|*.*") -> str:
    """弹系统「选择文件」对话框，返回路径（取消则空串）。"""
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms | Out-Null; "
        "$d = New-Object System.Windows.Forms.OpenFileDialog; "
        "$d.Filter = '%s'; "
        "$d.CheckFileExists = $true; "
        "if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { "
        "[Console]::Out.Write($d.FileName) }" % filter_desc.replace("'", "''")
    )
    flags = 0x08000000 if sys.platform == "win32" else 0
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", ps],
            capture_output=True, timeout=300, creationflags=flags,
        )
        return r.stdout.decode("utf-8", "ignore").strip()
    except Exception:
        return ""


TOOL_KEYS = ("uasset", "fmodel", "dumper", "uasset_mapping", "dumper_dll", "dump_out")


def _path_state(path: str) -> dict:
    pth = (path or "").strip().strip('"')
    if not pth:
        return {"path": "", "exists": False, "size": 0}
    pp = Path(pth)
    ok = pp.is_file()
    return {"path": pth, "exists": ok, "size": (pp.stat().st_size if ok else 0)}


def tool_state() -> dict:
    v = _vars()
    out = {}
    for k in ("uasset", "fmodel", "dumper", "uasset_mapping", "dumper_dll"):
        out[k] = _path_state(str(v.get(k) or ""))
    out["dump_out"] = {"path": str(v.get("dump_out") or ""), "exists": bool(str(v.get("dump_out") or ""))}
    return out


def _proc_list() -> list:
    """枚举带窗口/常见进程：tasklist 给 pid+名字，能拿到镜像路径的补上。"""
    flags = 0x08000000 if sys.platform == "win32" else 0
    try:
        r = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True,
                           timeout=30, creationflags=flags)
        txt = r.stdout.decode("gbk", "ignore")
    except Exception:
        return []
    rows = []
    for line in txt.splitlines():
        parts = [x.strip('"') for x in line.split('","')]
        if len(parts) < 2:
            continue
        name, pid = parts[0].strip('"'), parts[1].strip('"')
        if not pid.isdigit():
            continue
        rows.append({"pid": int(pid), "name": name})
    rows.sort(key=lambda x: x["name"].lower())
    return rows


def inject_dll(pid: int, dll: str) -> dict:
    """把 dll 注入到指定进程（LoadLibraryW 远程线程），返回结果。"""
    if _ct is None:
        return {"ok": False, "error": "ctypes 不可用"}
    dllp = str(Path(dll).resolve())
    if not Path(dllp).is_file():
        return {"ok": False, "error": "找不到 dll：" + dllp}
    k32 = _ct.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = _ct.c_void_p
    k32.OpenProcess.argtypes = [_ct.c_ulong, _ct.c_int, _ct.c_ulong]
    k32.VirtualAllocEx.restype = _ct.c_void_p
    k32.VirtualAllocEx.argtypes = [_ct.c_void_p, _ct.c_void_p, _ct.c_size_t, _ct.c_ulong, _ct.c_ulong]
    k32.WriteProcessMemory.argtypes = [_ct.c_void_p, _ct.c_void_p, _ct.c_char_p, _ct.c_size_t, _ct.POINTER(_ct.c_size_t)]
    k32.GetProcAddress.restype = _ct.c_void_p
    k32.GetProcAddress.argtypes = [_ct.c_void_p, _ct.c_char_p]
    k32.CreateRemoteThread.restype = _ct.c_void_p
    k32.CreateRemoteThread.argtypes = [_ct.c_void_p, _ct.c_void_p, _ct.c_size_t, _ct.c_void_p, _ct.c_void_p, _ct.c_ulong, _ct.c_void_p]
    k32.CloseHandle.argtypes = [_ct.c_void_p]
    PROCESS_ALL = 0x1F0FFF
    MEM_COMMIT_RESERVE = 0x3000
    PAGE_RWX = 0x40
    h = k32.OpenProcess(PROCESS_ALL, False, int(pid))
    if not h:
        return {"ok": False, "error": "OpenProcess 失败（权限不足？请用管理员运行）err=%d" % _ct.get_last_error()}
    try:
        buf = dllp.encode("utf-16-le") + b"\x00\x00"
        size = len(buf)
        addr = k32.VirtualAllocEx(h, None, size, MEM_COMMIT_RESERVE, PAGE_RWX)
        if not addr:
            return {"ok": False, "error": "VirtualAllocEx 失败 err=%d" % _ct.get_last_error()}
        wrote = _ct.c_size_t(0)
        if not k32.WriteProcessMemory(h, addr, buf, size, _ct.byref(wrote)):
            return {"ok": False, "error": "WriteProcessMemory 失败 err=%d" % _ct.get_last_error()}
        hmod = k32.GetModuleHandleW("kernel32.dll")
        fn = k32.GetProcAddress(hmod, b"LoadLibraryW")
        th = k32.CreateRemoteThread(h, None, 0, fn, addr, 0, None)
        if not th:
            return {"ok": False, "error": "CreateRemoteThread 失败 err=%d" % _ct.get_last_error()}
        k32.WaitForSingleObject.argtypes = [_ct.c_void_p, _ct.c_ulong]
        k32.WaitForSingleObject(th, 8000)
        code = _ct.c_ulong(0)
        k32.GetExitCodeThread.argtypes = [_ct.c_void_p, _ct.POINTER(_ct.c_ulong)]
        k32.GetExitCodeThread(th, _ct.byref(code))
        k32.CloseHandle(th)
        return {"ok": True, "pid": int(pid), "dll": dllp, "ret": int(code.value)}
    finally:
        k32.CloseHandle(h)



try:
    import ctypes as _ct
except Exception:
    _ct = None

_WINRS: dict = {}


def win_action(action: str):
    """最小化 / 最大化 / 关闭 / 拖动 —— 由页面按钮通过本地 HTTP 调用。"""
    import ctypes
    from ctypes import wintypes

    if sys.platform != "win32":
        return False
    u = ctypes.windll.user32
    h = _hwnd()
    if not h:
        return False

    if action == "minimize":
        class RMIN(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                        ("r", ctypes.c_long), ("b", ctypes.c_long)]
        rmin = RMIN()
        u.GetWindowRect(wintypes.HWND(h), ctypes.byref(rmin))
        _WINRS["pre_min"] = [rmin.l, rmin.t, rmin.r - rmin.l, rmin.b - rmin.t]
        u.ShowWindow(wintypes.HWND(h), 6)          # SW_MINIMIZE
        return True
    if action == "maximize":
        u.ShowWindow(wintypes.HWND(h), 3)          # SW_MAXIMIZE
        return True
    if action == "restore":
        u.ShowWindow(wintypes.HWND(h), 9)          # SW_RESTORE
        r = _WINRS.get("pre_min")
        if r:
            # WinForms 的 RestoreBounds 与我们 SetWindowPos 过的尺寸不一致，会逐次缩水，这里钉回去
            u.SetWindowPos(wintypes.HWND(h), None, r[0], r[1], r[2], r[3], 0x0004 | 0x0010)
        return True
    if action == "toggle_max":
        # 无边框窗口用 SW_MAXIMIZE 会多出约 6px 边框溢出，这里自己贴工作区
        class MRECT(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                        ("r", ctypes.c_long), ("b", ctypes.c_long)]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", MRECT),
                        ("rcWork", MRECT), ("dwFlags", ctypes.c_ulong)]

        hwnd = wintypes.HWND(h)
        st = _WINRS
        if st.get("maxed"):
            r = st.get("restore_rect")
            if r:
                u.SetWindowPos(hwnd, None, r[0], r[1], r[2], r[3], 0x0004 | 0x0010)
            st["maxed"] = False
            return True
        rc = MRECT()
        u.GetWindowRect(hwnd, ctypes.byref(rc))
        st["restore_rect"] = [rc.l, rc.t, rc.r - rc.l, rc.b - rc.t]
        hmon = u.MonitorFromWindow(hwnd, 2)   # MONITOR_DEFAULTTONEAREST
        mi = MONITORINFO(); mi.cbSize = ctypes.sizeof(MONITORINFO)
        work = rc
        if hmon and u.GetMonitorInfoW(wintypes.HANDLE(hmon), ctypes.byref(mi)):
            work = mi.rcWork
        u.SetWindowPos(hwnd, None, work.l, work.t, work.r - work.l, work.b - work.t, 0x0004 | 0x0010)
        st["maxed"] = True
        return True
    if action in ("resize_begin", "resize_tick", "resize_end"):
        class PT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class RC(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                        ("r", ctypes.c_long), ("b", ctypes.c_long)]

        st = _WINRS.setdefault("job", {})
        hwnd = wintypes.HWND(h)
        if action == "resize_begin":
            pt = PT(); u.GetCursorPos(ctypes.byref(pt))
            rc = RC(); u.GetWindowRect(hwnd, ctypes.byref(rc))
            st.clear()
            st.update(edge=str(_WINRS.get("edge") or "e"), cx=pt.x, cy=pt.y,
                      l=rc.l, t=rc.t, r=rc.r, b=rc.b)
            return True
        if action == "resize_end":
            st.clear()
            return True
        if not st:
            return False
        pt = PT(); u.GetCursorPos(ctypes.byref(pt))
        dx, dy = pt.x - st["cx"], pt.y - st["cy"]
        e = st["edge"]
        left, top, right, bottom = st["l"], st["t"], st["r"], st["b"]
        if "e" in e: right = st["r"] + dx
        if "s" in e: bottom = st["b"] + dy
        if "w" in e: left = st["l"] + dx
        if "n" in e: top = st["t"] + dy
        mw, mh = 1120, 720
        if right - left < mw:
            if "w" in e: left = right - mw
            else: right = left + mw
        if bottom - top < mh:
            if "n" in e: top = bottom - mh
            else: bottom = top + mh
        u.SetWindowPos(hwnd, None, left, top, right - left, bottom - top, 0x0004 | 0x0010)
        _WINRS["last"] = {"edge": e, "dx": dx, "dy": dy,
                          "rect": [left, top, right - left, bottom - top]}
        return True

    if action == "close":
        u.PostMessageW(wintypes.HWND(h), 0x0010, 0, 0)   # WM_CLOSE
        return True
    if action == "drag_begin":
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class RECT(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                        ("r", ctypes.c_long), ("b", ctypes.c_long)]
        pt, rc = POINT(), RECT()
        u.GetCursorPos(ctypes.byref(pt))
        u.GetWindowRect(wintypes.HWND(h), ctypes.byref(rc))
        _drag["cur"], _drag["rect"] = (pt.x, pt.y), (rc.l, rc.t)
        return True
    if action == "drag_tick":
        if not _drag["cur"] or not _drag["rect"]:
            return False
        class POINT2(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        p2 = POINT2()
        u.GetCursorPos(ctypes.byref(p2))
        dx = p2.x - _drag["cur"][0]
        dy = p2.y - _drag["cur"][1]
        u.SetWindowPos(wintypes.HWND(h), None,
                       _drag["rect"][0] + dx, _drag["rect"][1] + dy,
                       0, 0, 0x0001 | 0x0004 | 0x0010)
        return True
    if action == "drag_end":
        _drag["cur"] = _drag["rect"] = None
        return True
    return False


def aeskeys() -> list[dict]:
    path = tool_dir() / AESKEY_NAME
    out = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [x.strip() for x in line.split("\t")]
        key = parts[0]
        if not re.fullmatch(r"[0-9a-fA-F]{64}", key):
            continue
        note = parts[2] if len(parts) > 2 else ""
        out.append({"key": key.lower(),
                    "how": parts[1] if len(parts) > 1 else "",
                    "note": note,
                    "game": game_name(note)})
    return out


# ---------------------------------------------------------------- 命令拼装
TOKEN = re.compile(r"\{([a-zA-Z0-9_:]+)\}")


def _vars() -> dict:
    cat = catalog()
    v = dict(cat.get("vars", {}))
    # 用户设置覆盖内置默认（catalog 打包在 exe 里是只读的）
    for k, val in (read_json(SETTINGS_JSON, {}) or {}).items():
        if val:
            v[k] = val
    v["node"] = node_exe()
    v["py"] = python_exe()
    v["tool"] = v.get("tool", "")
    v["pwsh"] = v.get("pwsh", "powershell.exe")
    v["localappdata"] = os.environ.get("LOCALAPPDATA", "")
    v["out"] = str(HERE)
    v["outdir"] = v.get("outdir") or str(HERE / "output")
    try:
        os.makedirs(v["outdir"], exist_ok=True)
    except Exception:
        pass
    v["app"] = str(HERE if (HERE / "tools").exists() else BUNDLE)  # 内置工具根目录 = exe 所在目录
    tgt = read_json(TARGET_JSON, {})
    v.update({k: tgt.get(k, "") for k in ("game", "exe", "pak", "utoc", "ucas")})
    # 变量里可能嵌套占位符（如 tool = "{app}\\tools\\UEKeyHunter"），展开到稳定
    for _ in range(4):
        changed = False
        for k, val in list(v.items()):
            if not isinstance(val, str) or "{" not in val:
                continue
            expanded = re.sub(r"\{([a-zA-Z0-9_]+)\}", lambda m: str(v.get(m.group(1), m.group(0))), val)
            if expanded != val:
                v[k] = expanded
                changed = True
        if not changed:
            break
    return v


def find_task(task_id: str):
    for mod in catalog().get("modules", []):
        for t in mod.get("tasks", []) or []:
            if t.get("id") == task_id:
                return t
    return None


def build_cmd(task_id: str, params: dict) -> tuple[list[str], str]:
    task = find_task(task_id)
    if not task:
        raise ValueError("catalog 里没有任务 " + task_id)

    base = _vars()
    vals: dict[str, object] = {}
    for p in task.get("params", []):
        d = p.get("default")
        if d:
            vals[p["id"]] = TOKEN.sub(lambda m: str(base.get(m.group(1), "")), d)
    for pid, val in params.items():
        if isinstance(val, bool):
            vals[pid] = val
        elif str(val).strip():
            vals[pid] = str(val).strip()

    # 输出目录：给了 outdir 又没写具体输出文件时，自动拼上默认文件名
    od = vals.get("outdir") or base.get("outdir")
    if od:
        for key in ("out", "csv"):
            if not vals.get(key):
                vals[key] = os.path.join(str(od), str(task.get("outDefault") or "output.csv"))
                break

    def expand(tok: str) -> str:
        def rep(m):
            name = m.group(1)
            if name.startswith("p:"):
                return str(vals.get(name[2:], ""))
            if name.startswith("f:"):
                return ""
            return str(base.get(name, m.group(0)))
        return TOKEN.sub(rep, tok)

    argv: list[str] = []
    for tok in task.get("cmd", []):
        m = re.fullmatch(r"\{f:([^:}]+):(.+)\}", tok)
        if m:
            if vals.get(m.group(1)):
                argv.append(m.group(2))
            continue
        # {j:param:--flag} → 有值时展开成 "--flag=值" 一个 token（值以 - 开头时必须用这个）
        j = re.fullmatch(r"\{j:([^:}]+):(.+)\}", tok)
        if j:
            v = vals.get(j.group(1))
            if v not in (None, "", False):
                argv.append(f"{j.group(2)}={v}")
            continue
        # {k:param:--flag} → 有值时展开成 "--flag 值" 两个 token
        k = re.fullmatch(r"\{k:([^:}]+):(.+)\}", tok)
        if k:
            v = vals.get(k.group(1))
            if v not in (None, "", False):
                argv += [k.group(2), str(v)]
            continue
        names = re.findall(r"\{p:([^}]+)\}", tok)
        if names and any(not vals.get(n) for n in names):
            continue
        argv.append(expand(tok))
    if not argv:
        raise ValueError("命令模板为空")
    return argv, subprocess.list2cmdline(argv)


# ---------------------------------------------------------------- 子进程
def _run_capture(argv: list[str], timeout: int = 60) -> str:
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    try:
        r = subprocess.run(argv, cwd=str(tool_dir() or HERE), stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                           creationflags=CREATE_NO_WINDOW, env=env, timeout=timeout)
        return r.stdout.decode("utf-8", "replace")
    except Exception as e:
        return "ERROR: " + str(e)


def _pump(job: dict, proc: subprocess.Popen) -> None:
    for stream in (proc.stdout, proc.stderr):
        if stream is None:
            continue
        for raw in iter(stream.readline, b""):
            try:
                line = raw.decode("utf-8").rstrip("\r\n")
            except UnicodeDecodeError:
                # 有些老工具（raosig 等）仍按 GBK 输出，回退一次
                line = raw.decode("gbk", "replace").rstrip("\r\n")
            with LOCK:
                job["lines"].append(line)
    rc = proc.wait()
    with LOCK:
        job["rc"] = rc
        job["done"] = True


def detect_targets(game: str) -> dict:
    g = Path(game)
    found = {"game": str(g)}
    if not g.exists():
        return found
    for pat in ("**/Binaries/Win64/*-Win64-Shipping.exe", "**/*Shipping.exe", "**/*.exe"):
        hits = sorted(g.glob(pat), key=lambda p: p.stat().st_size, reverse=True)
        if hits:
            found["exe"] = str(hits[0])
            break
    paks = []
    for pat in ("**/Content/Paks/*.pak", "**/Paks/*.pak"):
        paks += list(g.glob(pat))
    if paks:
        paks = sorted(set(paks), key=lambda p: p.stat().st_size, reverse=True)
        found["pak"] = str(paks[0])
        found["pak_count"] = len(paks)
    return found


# ---------------------------------------------------------------- HTTP
class Handler(SimpleHTTPRequestHandler):
    server_version = "TIToolbox/1.0"

    # Windows 注册表把 .js 映射成 text/plain，浏览器会拒绝执行 <script src>，
    # 这里显式声明常见静态类型。
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "application/javascript",
        ".mjs": "application/javascript",
        ".css": "text/css",
        ".json": "application/json",
        ".map": "application/json",
        ".webp": "image/webp",
        ".png": "image/png",
        ".ico": "image/x-icon",
        ".svg": "image/svg+xml",
        ".woff2": "font/woff2",
    }

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(UI), **kw)

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        if self.path.startswith("/api/catalog"):
            return self._json({"ok": True, "catalog": catalog(), "vars": _vars()})
        if self.path.startswith("/api/settings"):
            return self._json({"ok": True, "settings": _vars(),
                               "saved": read_json(SETTINGS_JSON, {})})
        if self.path.startswith("/api/state"):
            return self._json({
                "target": read_json(TARGET_JSON, {}),
                "aeskeys": aeskeys(),
                "tool_dir": str(tool_dir()),
                "node": node_exe(),
            })
        if self.path.startswith("/api/log"):
            q = parse_qs(urlparse(self.path).query)
            jid = (q.get("id") or [""])[0]
            since = int((q.get("since") or ["0"])[0])
            job = JOBS.get(jid)
            if not job:
                return self._json({"error": "no such job"})
            with LOCK:
                return self._json({"lines": job["lines"][since:], "done": job["done"], "rc": job["rc"]})
        p0 = self.path.split("?")[0]
        if p0 in ("/", "/index.html"):
            try:
                html = (HERE / "ui" / "index.html").read_text(encoding="utf-8")
                th = str(read_json(SETTINGS_JSON, {}).get("theme") or "").lower()
                if th in ("light", "dark", "pink"):
                    # 内联脚本形如 (_t==="dark"||_t==="pink")?_t:"light"，
                    # 把末尾兜底值换成已保存的主题，首帧就不会闪。
                    html = re.sub(r'(\?_t\s*:\s*)"light"', r'\1"%s"' % th, html, count=1)
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            except Exception:
                pass
        return super().do_GET()

    def do_POST(self):
        p = self.path.split("?")[0]
        data = self._body()

        if p == "/api/changelog":
            f = HERE / "changelog.md"
            txt = ""
            try:
                if f.exists():
                    txt = f.read_text(encoding="utf-8")
            except Exception:
                txt = ""
            return self._json({"ok": True, "text": txt})

        if p == "/api/pick":
            if data.get("dry"):
                return self._json({"ok": True, "path": "", "dry": True})
            return self._json({"ok": True, "path": pick_dir()})

        if p == "/api/listassets":
            d = (data.get("dir") or "").strip().strip('"')
            limit = int(data.get("limit") or 1200)
            if not d or not os.path.isdir(d):
                return self._json({"ok": False, "error": "目录不存在：" + (d or "(空)"), "counts": {}, "items": []})
            exts = (".uasset", ".umap", ".uexp")
            counts = {"uasset": 0, "umap": 0, "uexp": 0}
            items = []
            base_depth = d.rstrip("\\/").count(os.sep) + 1
            for root, dirs, files in os.walk(d):
                dirs[:] = [x for x in dirs if not x.startswith(".")]
                if root.count(os.sep) + 1 - base_depth >= 6:
                    dirs[:] = []
                for fn in files:
                    low = fn.lower()
                    for e in exts:
                        if low.endswith(e):
                            counts[e[1:]] += 1
                            if len(items) < limit:
                                rel = os.path.relpath(os.path.join(root, fn), d).replace("\\", "/")
                                items.append(rel)
                            break
            counts["total"] = counts["uasset"] + counts["umap"] + counts["uexp"]
            items.sort(key=lambda x: x.lower())
            return self._json({"ok": True, "dir": d, "counts": counts, "items": items})
        if p == "/api/listdir":
            d = (data.get("dir") or "").strip().strip('"')
            ext = (data.get("ext") or "usmap").strip().lstrip("*.").lower()
            if not d or not os.path.isdir(d):
                return self._json({"ok": False, "error": "目录不存在：" + (d or "(空)"), "files": []})
            deep = bool(data.get("deep", True))
            try:
                if deep:
                    names = []
                    base = d.rstrip("\\/")
                    base_depth = base.count(os.sep)
                    for root, dirs, fns in os.walk(d):
                        dirs[:] = [x for x in dirs if not x.startswith(".")]
                        if root.count(os.sep) - base_depth >= 3:
                            dirs[:] = []
                        for f in fns:
                            if f.lower().endswith("." + ext):
                                rel = os.path.relpath(os.path.join(root, f), d)
                                names.append(rel.replace("\\", "/"))
                    names.sort(key=lambda x: x.lower())
                else:
                    names = sorted([f for f in os.listdir(d) if f.lower().endswith("." + ext)], key=lambda x: x.lower())
            except Exception as e:
                return self._json({"ok": False, "error": str(e), "files": []})
            return self._json({"ok": True, "dir": d, "deep": deep, "files": names})
        if p == "/api/ghcheck":
            repo = (data.get("repo") or "").strip()
            # 兼容 owner/repo 简写与完整 URL
            m = re.search(r"github\.com[/:]([^/\s]+)/([^/\s]+)", repo)
            if not m:
                m = re.search(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$", repo)
            if not m:
                return self._json({"ok": False, "error": "仓库地址无法识别，示例：https://github.com/owner/repo 或 owner/repo"})
            owner, name = m.group(1), m.group(2)
            if name.endswith(".git"):
                name = name[:-4]
            url = "https://api.github.com/repos/%s/%s/releases/latest" % (owner, name)
            try:
                hdrs = {
                    "User-Agent": "TI-Toolbox/" + str((json.loads(((HERE if (HERE / "catalog.json").exists() else BUNDLE) / "catalog.json").read_text(encoding="utf-8")).get("app", {}).get("version", "1.0.0"))),
                    "Accept": "application/vnd.github+json",
                }
                tok = (read_json(SETTINGS_JSON, {}) or {}).get("github_token") or ""
                if tok:
                    hdrs["Authorization"] = "Bearer " + tok
                req = urllib.request.Request(url, headers=hdrs)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    info = json.loads(resp.read().decode("utf-8"))
                return self._json({"ok": True, "repo": owner + "/" + name, "tag": info.get("tag_name") or "",
                                   "name": info.get("name") or "", "url": info.get("html_url") or "",
                                   "published": info.get("published_at") or ""})
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return self._json({"ok": False, "error": "该仓库没有 Release，或仓库不存在（404）"})
                if e.code == 403:
                    return self._json({"ok": False, "error": "GitHub 接口配额已用尽（403），请稍后再试或填写 token"})
                return self._json({"ok": False, "error": "GitHub 返回 %d" % e.code})
            except Exception as e:
                return self._json({"ok": False, "error": "请求 GitHub 失败：" + str(e)})
        if p == "/api/locres":
            src = (data.get("path") or "").strip().strip('"')
            if not src or not os.path.isfile(src):
                return self._json({"ok": False, "error": "文件不存在：" + (src or "(空)"), "count": 0, "entries": []})
            tool = os.path.join(str(HERE), "tools", "UnrealLocres", "UnrealLocres.exe")
            if not os.path.isfile(tool):
                return self._json({"ok": False, "error": "缺少 tools/UnrealLocres/UnrealLocres.exe", "count": 0, "entries": []})
            tmp = tempfile.mkdtemp(prefix="tiloc_")
            out = os.path.join(tmp, "loc.csv")
            try:
                cp = subprocess.run([tool, "export", src, "-o", out], capture_output=True,
                                    timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except Exception as e:
                return self._json({"ok": False, "error": "导出失败：" + str(e), "count": 0, "entries": []})
            if not os.path.isfile(out):
                msg = (cp.stderr or cp.stdout or b"").decode("utf-8", "replace")[-400:]
                return self._json({"ok": False, "error": "导出失败：" + msg, "count": 0, "entries": []})
            rows = []
            try:
                with open(out, "r", encoding="utf-8-sig", newline="") as f:
                    rd = csv.reader(f)
                    header = next(rd, None)
                    for r in rd:
                        if not r:
                            continue
                        rows.append({"key": r[0] if len(r) > 0 else "",
                                     "source": r[1] if len(r) > 1 else "",
                                     "target": r[2] if len(r) > 2 else ""})
            except Exception as e:
                return self._json({"ok": False, "error": "解析 CSV 失败：" + str(e), "count": 0, "entries": []})
            limit = int(data.get("limit") or 600)
            return self._json({"ok": True, "path": src, "count": len(rows),
                               "entries": rows[:limit], "truncated": len(rows) > limit})
        if p == "/api/clipboard":
            txt = ""
            try:
                import ctypes
                from ctypes import wintypes
                CF_UNICODETEXT = 13
                GMEM_MOVEABLE = 0x0002
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                k32 = ctypes.WinDLL("kernel32", use_last_error=True)
                user32.OpenClipboard.argtypes = [wintypes.HWND]
                user32.OpenClipboard.restype = wintypes.BOOL
                user32.GetClipboardData.argtypes = [wintypes.UINT]
                user32.GetClipboardData.restype = wintypes.HANDLE
                user32.CloseClipboard.restype = wintypes.BOOL
                k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
                k32.GlobalLock.restype = wintypes.LPVOID
                k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
                k32.GlobalUnlock.restype = wintypes.BOOL
                k32.GlobalSize.argtypes = [wintypes.HGLOBAL]
                k32.GlobalSize.restype = ctypes.c_size_t
                ok = False
                for _ in range(6):
                    if user32.OpenClipboard(None):
                        ok = True
                        break
                    time.sleep(0.05)
                if not ok:
                    return self._json({"ok": False, "error": "剪贴板正被其它程序占用", "text": ""})
                try:
                    h = user32.GetClipboardData(CF_UNICODETEXT)
                    if h:
                        n = k32.GlobalSize(h)
                        ptr = k32.GlobalLock(h)
                        if ptr:
                            try:
                                txt = ctypes.wstring_at(ptr, max(0, n // 2))
                            finally:
                                k32.GlobalUnlock(h)
                finally:
                    user32.CloseClipboard()
            except Exception as e:
                return self._json({"ok": False, "error": "读取剪贴板失败：" + str(e), "text": ""})
            txt = (txt or "").split("\x00")[0].strip().strip('"').strip("'")
            return self._json({"ok": True, "text": txt})
        if p == "/api/pickfile":
            return self._json({"ok": True, "path": pick_file(data.get("filter") or "可执行文件 (*.exe)|*.exe|所有文件 (*.*)|*.*")})

        if p == "/api/toolstate":
            return self._json({"ok": True, "state": tool_state()})

        if p == "/api/procs":
            return self._json({"ok": True, "procs": _proc_list()})

        if p == "/api/inject":
            try:
                pid = int(data.get("pid") or 0)
            except Exception:
                pid = 0
            dll = str(data.get("dll") or "").strip().strip('"')
            if not pid or not dll:
                return self._json({"ok": False, "error": "需要 pid 和 dll"})
            return self._json(inject_dll(pid, dll))

        if p == "/api/target":
            cur = read_json(TARGET_JSON, {})
            for k, v in data.items():
                if v:
                    cur[k] = v
            write_json(TARGET_JSON, cur)
            return self._json({"ok": True, "target": cur})

        if p == "/api/detect":
            game = data.get("game") or ""
            if not game or not Path(game).exists():
                return self._json({"ok": False, "error": "目录不存在"})
            return self._json({"ok": True, "found": detect_targets(game)})

        if p == "/api/pakpreview":
            pak = (data.get("pak") or "").strip().strip('"')
            if not pak or not Path(pak).exists():
                return self._json({"ok": False, "error": "pak not found"})
            aes = (data.get("aes") or "").strip()
            v = _vars()
            repak = v.get("repak") or "repak"
            base = [repak] + (["--aes-key", aes] if aes else [])
            info = _run_capture(base + ["info", pak])
            listing = _run_capture(base + ["list", pak])
            rows = [x for x in listing.splitlines() if x.strip()]
            return self._json({"ok": True, "info": info.strip(), "list": listing, "count": len(rows)})

        if p == "/api/run":
            try:
                argv, shown = build_cmd(data.get("task") or "", data.get("params") or {})
            except Exception as e:
                return self._json({"ok": False, "error": str(e)})
            job_id = uuid.uuid4().hex[:12]
            try:
                env = dict(os.environ)
                env.setdefault("PYTHONIOENCODING", "utf-8")
                env.setdefault("PYTHONUTF8", "1")
                proc = subprocess.Popen(
                    argv, cwd=str(tool_dir() or HERE),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW, env=env,
                )
            except Exception as e:
                return self._json({"ok": False, "error": str(e)})
            job = {"id": job_id, "lines": ["$ " + shown], "done": False, "rc": None,
                   "proc": proc, "t0": time.time(), "cmd": shown}
            JOBS[job_id] = job
            threading.Thread(target=_pump, args=(job, proc), daemon=True).start()
            return self._json({"ok": True, "id": job_id, "cmd": shown})

        if p == "/api/launch":
            direct = (data.get("exe") or "").strip().strip('"')
            if direct:
                argv, shown = [direct], direct
            else:
                try:
                    argv, shown = build_cmd(data.get("task") or "", data.get("params") or {})
                except Exception as e:
                    return self._json({"ok": False, "error": str(e)})
            exe = argv[0]
            if not os.path.exists(exe):
                return self._json({"ok": False, "error": "找不到程序：" + exe})
            try:
                subprocess.Popen(
                    argv, cwd=str(Path(exe).parent),
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                )
            except Exception as e:
                return self._json({"ok": False, "error": str(e)})
            return self._json({"ok": True, "cmd": shown})

        if p == "/api/stop":
            job = JOBS.get(data.get("id") or "")
            if job and job["proc"].poll() is None:
                job["proc"].kill()
                return self._json({"ok": True})
            return self._json({"ok": False, "error": "没有在跑的任务"})

        if p == "/api/settings":
            cur = read_json(SETTINGS_JSON, {})
            for k in ("tool", "node", "pwsh", "theme", "lang", "outdir", "uasset", "fmodel", "dumper",
              "uasset_mapping", "dumper_dll", "dump_out",
              "mapping_dir", "uasset_mapping_dir", "fmodel_mapping_dir",
              "dump_mapping", "dump_wait", "github_repo"):
                if k in data and str(data[k]).strip():
                    cur[k] = str(data[k]).strip()
            perf = data.get("perf")
            if isinstance(perf, dict):
                merged = dict(cur.get("perf") or {})
                merged.update({k: bool(v) for k, v in perf.items() if k in ("noAnim", "gpu")})
                cur["perf"] = merged
            write_json(SETTINGS_JSON, cur)
            return self._json({"ok": True, "settings": _vars(), "saved": cur})

        if p == "/api/clearcache":
            removed = 0
            for f in list(HERE.glob("_*")):
                try:
                    f.unlink()
                    removed += 1
                except Exception:
                    pass
            return self._json({"ok": True, "removed": removed, "outdir": str(_vars().get("outdir"))})

        if p == "/api/win":
            act = str(data.get("action") or "")
            _WINRS["edge"] = str(data.get("edge") or "e")
            okk = bool(win_action(act))
            out = {"ok": okk, "action": act}
            return self._json(out)

        if p == "/api/link":
            url = str(data.get("url") or "").strip()
            try:
                from urllib.parse import urlparse

                u = urlparse(url)
                host = (u.hostname or "").lower()
                if u.scheme not in ("https", "http") or not host.endswith("ifdian.net"):
                    return self._json({"ok": False, "error": "host not allowed"}, 400)
                os.startfile(url)
            except Exception as exc:  # noqa: BLE001
                return self._json({"ok": False, "error": str(exc)}, 500)
            return self._json({"ok": True, "url": url})

        if p == "/api/open":
            what = data.get("what") or "tool"
            if what == "key":
                f = tool_dir() / AESKEY_NAME
                if f.exists():
                    os.startfile(str(f))
            elif what == "app":
                os.startfile(str(HERE))
            else:
                d = tool_dir()
                if d.exists():
                    os.startfile(str(d))
            return self._json({"ok": True})

        return self._json({"ok": False, "error": "unknown endpoint"}, 404)


def pick_port(start=8777, tries=40) -> int:
    for p in range(start, start + tries):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return start


def main() -> int:
    port = pick_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("TI工具箱  http://127.0.0.1:%d/" % port)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
