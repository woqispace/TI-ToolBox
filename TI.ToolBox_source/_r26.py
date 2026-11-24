# -*- coding: utf-8 -*-
"""ROUND 26: expand {app} before creating the output folder (no stray '{app}' dir)."""
import pathlib

p = pathlib.Path(r"F:\模型\TI工具箱\app.py")
src = p.read_text(encoding="utf-8")

old = '''    v["out"] = str(HERE)
    v["outdir"] = v.get("outdir") or str(HERE / "output")
    try:
        os.makedirs(v["outdir"], exist_ok=True)
    except Exception:
        pass
    v["app"] = str(HERE if (HERE / "tools").exists() else BUNDLE)  # 内置工具根目录 = exe 所在目录
'''
new = '''    v["out"] = str(HERE)
    v["app"] = str(HERE if (HERE / "tools").exists() else BUNDLE)  # 内置工具根目录 = exe 所在目录
    # ROUND 26: 先把 {app} 展开再建目录，否则会在 exe 旁边建出一个字面量 "{app}" 文件夹
    v["outdir"] = (v.get("outdir") or str(HERE / "output")).replace("{app}", v["app"])
    try:
        os.makedirs(v["outdir"], exist_ok=True)
    except Exception:
        pass
'''
assert old in src, "outdir anchor missing"
src = src.replace(old, new, 1)
p.write_text(src, encoding="utf-8")
print("py_ok", len(src))
