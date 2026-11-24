# TI 工具箱

一个把 **UE4 / UE5 资源处理与汉化流程**收进单窗口的桌面工具箱。

从「在游戏里找 pak 密钥」到「把翻译好的文本重新打进 pak」，这条链路上原本要在七、八个命令行工具之间来回倒腾：解包要 repak、IoStore 要 retoc、locres 要 UnrealLocres、资产要 UAssetGUI、映射要 dumper、签名补丁还要自己拼启动参数。TI 工具箱把这些事情做成一个个可视化面板——路径填一次就记住，参数按工具各自留存，输出与报错直接显示在窗口里，不用再开一堆终端。

它是**单文件绿色程序**：一个 `TI工具箱.exe`，双击即用，不写注册表，不改系统环境。

---

## 它解决什么问题

- **拿到 pak 打不开**：不知道 AES 密钥，或知道密钥但不知道对不对。
- **改完文本打不回去**：locres / uasset 里的字符串取不出来，取出来也写不回去。
- **补丁包被引擎拒收**：pak 签名校验挡住了自己做的汉化包。
- **工具太多、参数记不住**：每次都要翻笔记找那条 repak / retoc 命令。
- **改完不知道有没有改对**：缺一个能当场看 key / source / target 的地方。

---

## 功能一览

十个面板，按「密钥 → 解包 → 文本 → 打包 → 验签」的实际顺序排列。

| 面板 | 作用 |
|---|---|
| **AES 提取** | 五路挖 pak 密钥：扫 exe 立即数、扫进程内存、扫文本、解 DPAPI 缓存、校验已有 key。命中后用 pak 索引的 SHA-1 反查真伪，只留真的。 |
| **文本** | locres 导出为 CSV（key / source / target 三列）、改完导入回 locres、从资产生成 locres、uasset 文本定位与批量替换、字体转 ufont。 |
| **绕签名** | 生成代理 DLL，给引擎补上 `-fileopenlog` 等启动参数，让未签名的补丁 pak 能被加载；支持一键卸载。 |
| **解包** | 普通 `.pak` 走 repak，IoStore（`.utoc` / `.ucas`）走 retoc；可带 AES key、可强制覆盖。 |
| **打包** | 同样两条通道反着来：目录 → pak，或目录 → IoStore，挂载点与前缀可填。 |
| **资产查看** | 指向解包后的 `Content` 目录，递归列出 `.uasset` / `.umap` / `.uexp` 并统计；内置 LOCRES 查看器，选中就能看条目。 |
| **FMODEL** | 检测 FModel 路径、指定它用的 `.usmap` 映射、一键启动。 |
| **DUMP** | 检测 Dumper-7 与 jmap_dumper，枚举目标进程、注入 DLL、生成 `.usmap` 映射。 |
| **仓库** | 从 GitHub 拉工具清单并安装（开发中）。 |
| **主页** | 更新日志 + 更新计划两个页签，一个胶囊收起展开。 |

配套的小东西也都做了：三种主题（黑 / 白 / 粉，**默认白色**）、中英双语界面、路径输入历史、Mappings 文件夹递归识别（≤3 层）、每个工具的独立参数与状态徽标（已安装 / 未安装 / 默认）。

---

## 快速开始

1. 解压发布包，双击 `TI工具箱.exe`。
2. 左下角齿轮 → **设置**：填工具箱根目录、默认输出目录、Mappings 文件夹。
3. 侧栏选一个面板，按提示填路径或点「选择」。
4. 点「开始」，输出与进度直接显示在面板下方的输出框里。

设置改过之后才会在同目录生成 `settings.json`；不改就是纯默认值运行，删掉它等于恢复出厂。

**运行环境**：Windows 10 / 11，需要 [WebView2 运行时](https://developer.microsoft.com/microsoft-edge/webview2/)（Win11 自带，Win10 多数已随 Edge 装上）。

---

## 内置与外部工具

`tools/` 里随包分发的：

```
repak/          普通 pak 解包与打包
retoc/          IoStore（.utoc / .ucas）解包与打包
UnrealLocres/   locres 与 CSV 互转
UEKeyHunter/    密钥扫描脚本
STFinder/       uasset 字符串定位
LocCheck/       locres 校验
raosig/         绕签名用的代理 DLL 生成器
```

需要你自己准备、在面板里指路径的：

- **UAssetGUI** —— 资产查看 / uasset 文本
- **FModel** —— 模型与资产浏览
- **Dumper-7.dll + jmap_dumper** —— 生成 `.usmap` 映射

这些第三方工具由各自作者开发并保留全部权利，TI 工具箱只负责调用与整合。

---

## 目录结构

```
app.py              本地 HTTP API：任务执行、设置读写、文件与目录选择、LOCRES 解析
desktop.py          pywebview 无边框窗口（含标题栏按钮与窗口拖拽）
catalog.json        工具与任务的声明式清单（模块、参数、标签、版本号来源）
changelog.md        更新日志（主页「更新日志」页签读取）
ui/
  index.html        界面骨架
  app.js            渲染、交互、任务调度、主题与语言
  style.css         全部样式（三种主题）
  i18n.js           界面文案词典（中文 → English）
  i18n.catalog.js   catalog 文案的英文补充
  i18n.extra.js     工具面板与空态文案的英文补充
  logo*.webp / .ico 三套主题 logo 与程序图标
tools/              内置命令行工具（见上）
```

---

## 从源码构建

```powershell
pip install pywebview pyinstaller

python -m PyInstaller --noconfirm --clean --noconsole --onefile `
  --name "TI工具箱" --icon "ui\logo.ico" `
  --add-data "ui;ui" --add-data "catalog.json;." --add-data "changelog.md;." --add-data "tools;tools" `
  --hidden-import webview.platforms.edgechromium --collect-all webview desktop.py
```

产物在 `dist\TI工具箱.exe`。

**打包约定**（发布前照这个来）：

- 用**默认设置**打包：不带本机 `settings.json`、不带 `output/`、不带 `build/`、`dist/`、`__pycache__`、`*.spec`。
- 分发包里必须剔除 `tools/UEKeyHunter/AESKEY.txt`、`tools/UEKeyHunter/target.json` 这类本机密钥与目标配置。
- 版本号只写在 `catalog.json` 的 `app.version` 一处，界面与版本面板都从那里读。

---

## 版本与更新

当前版本见 `catalog.json` 的 `app.version`（同时显示在「设置 → 版本」左下角）。

「设置 → 版本」里填 GitHub 仓库地址即可检查更新；不填就只做本地版本展示。程序只在两处联网：检查更新、以及点「支持我」时用系统浏览器打开链接。

---

## 已知限制

- `retoc to-zen` 只处理已 cook 的 Zen 资产（`foo.uasset` + `foo.uexp` 分离）；单个 `.uasset` 会被跳过并提示没有 split exports 文件。
- 未签名 pak 依赖代理 DLL 注入启动参数，个别带反作弊或自定义启动器的游戏可能拦这一手。
- 密钥提取对加密方式做了适配的范围有限：非标准魔数、二次加密的包需要手工分析。
- 「仓库」面板（从 GitHub 直接装工具）还在做，当前为开发中。

---

## 反馈与支持

- 遇到问题先看面板输出框里的原始命令与报错，那里通常已经写明是路径、密钥还是参数的问题。
- 想支持这个项目：齿轮旁边的「支持我」。

---

## 免责声明

本工具面向**自己拥有或已获授权**的游戏与工程文件，仅用于个人学习、研究与本地化实践。

使用本工具修改、打包、注入或以其他方式处理文件所产生的全部后果由使用者自行承担；程序按「现状」提供，不对功能完整性、数据安全，以及由此导致的存档损坏、账号受限等损失作任何担保。

请勿将本工具用于商业分发、破解传播或任何侵犯他人著作权、违反当地法律法规的行为。

本工具不包含也不主张任何第三方工具的所有权。FModel、UAssetGUI、repak、retoc、jmap_dumper、Dumper-7、UnrealLocres 等均由各自作者开发并保留全部权利，使用前请阅读并遵守对应项目的许可条款。

使用即表示已阅读并同意上述条款；如不同意，请停止使用并删除本程序。
