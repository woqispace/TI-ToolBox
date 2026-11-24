/* TI Toolbox — catalog 文案英文字典（V1.1.2 补全）
   覆盖 catalog.json 里模块名/子标题/说明、任务 nav/title/desc、参数 label/placeholder/default。
   加载后合并进 window.I18N 并立即重译。 */
(function () {
  if (!window.I18N || !window.I18N.extend) return;

  window.I18N.extend({
    /* ---- 主页 ---- */
    '欢迎 · 更新日志': 'Welcome · Changelog',
    '首页': 'Home page',
    '欢迎页：打字欢迎语、署名人、右下角更新日志。':
      'Home: typed welcome line, signature, changelog at bottom right.',
    '游戏目录': 'Game folder',

    /* ---- AES 提取 / keys ---- */
    'exe / 代码 / 内存 / 文本 / DPAPI': 'exe / code / memory / text / DPAPI',
    '挖 pak 密钥': 'Dig out pak keys',
    '提取 PAK 的 AES-256 密钥：支持扫描可执行文件、代码立即数、内存转储、文本与 DPAPI 缓存，命中后以 PAK 索引 SHA-1 校验。':
      "Extracts a PAK's AES-256 key from the executable, code immediates, memory dumps, text files or the DPAPI cache; hits are verified against the PAK index SHA-1.",
    '扫 exe': 'Scan exe',
    '以滑动窗口遍历 EXE 中的 32 字节常量，命中后以 PAK 索引 SHA-1 校验。':
      'Walks 32-byte constants in the EXE with a sliding window; hits are verified against the PAK index SHA-1.',
    '例如 0x1000 或 4096': 'e.g. 0x1000 or 4096',
    '留空 = 扫到文件尾': 'Empty = scan to end of file',
    '扫代码': 'Scan code',
    '反汇编提取 MOV / LEA 拼装的 32 字节常量，效率高于全文件扫描。':
      'Disassembles MOV / LEA sequences that build 32-byte constants; faster than a whole-file scan.',
    '最多几个候选': 'Max candidates',
    '默认 200': 'Default 200',
    '只看候选（按熵排，不验 pak）': 'Candidates only (by entropy, no pak check)',
    '扫描内存转储': 'Scan memory dump',
    '在进程内存转储中检索明文密钥；需先将转储放入工具目录的 mem\\。':
      'Searches process memory dumps for a plaintext key; put dumps into mem\\ under the tool folder first.',
    'dump 目录（空 = <游戏目录>\\mem）': 'Dump folder (empty = <game>\\mem)',
    '留空自动拼': 'Empty = auto',
    '快速模式（大步长）': 'Fast mode (large stride)',
    '扫描文本中的密钥': 'Scan keys in text',
    '在游戏目录的脚本、配置与文档中检索 64 位十六进制串，并以 PAK 索引校验。':
      'Searches scripts, configs and docs in the game folder for 64-hex strings and verifies them against the PAK index.',
    '扫描目录（空 = 游戏目录）': 'Scan folder (empty = game folder)',
    '留空就用上面的游戏目录': 'Empty = use the game folder above',
    '单文件上限（字节）': 'Per-file limit (bytes)',
    '默认 4 MiB': 'Default 4 MiB',
    '解密 DPAPI 缓存': 'Decrypt DPAPI cache',
    '调用 CryptUnprotectData 解密本地缓存的密钥；部分游戏以 DPAPI 保存。':
      'Calls CryptUnprotectData to decrypt locally cached keys; some games store them this way.',
    '缓存目录': 'Cache folder',
    '%LOCALAPPDATA%\\<游戏>\\': '%LOCALAPPDATA%\\<game>\\',
    '附加熵（可选）': 'Extra entropy (optional)',
    '例如 FallenDollRehost pak key v1': 'e.g. FallenDollRehost pak key v1',
    '校验指定密钥': 'Verify a given key',
    '以 64 位十六进制密钥解密 PAK 索引，SHA-1 匹配即有效。':
      'Decrypts the PAK index with a 64-hex key; a matching SHA-1 means it is valid.',
    'key（64 位 hex）': 'key (64-hex)',

    /* ---- 文本 ---- */
    'locres / 定位 / 字体': 'locres / locate / font',
    '文本回灌': 'Text round-trip',
    'locres 导出与回灌、资产内 FText 与裸串定位、字体替换。':
      'Export and re-import locres, locate FText and raw strings inside assets, and replace fonts.',
    '资产目录（解包后的 Content）': 'Asset folder (unpacked Content)',
    'locres 导出': 'Export locres',
    '导出 locres 为 CSV': 'Export locres as CSV',
    '将 .locres 解析为 key、source、target 三列，供翻译与回填。':
      'Parses .locres into key, source and target columns for translation and re-import.',
    '拖一个 .locres 进来': 'Drop a .locres here',
    '留空 = 同目录同名 .csv': 'Empty = same folder, same name .csv',
    '留空 = 设置里的默认输出目录': 'Empty = default output folder from settings',
    'locres 导入': 'Import locres',
    '回灌 CSV 至 locres': 'Import CSV back into locres',
    '以底包 locres 为基础写入 CSV 译文，CSV 中新增的 key 将作为新条目写入。':
      'Writes CSV translations onto the base locres; keys new in the CSV are appended as new entries.',
    '底包 locres': 'Base locres',
    '原始 .locres': 'Source .locres',
    '翻译 CSV': 'Translation CSV',
    '输出 locres': 'Output locres',
    '留空 = <底包名>_cn.locres': 'Empty = <base>_cn.locres',
    '资产生成 locres': 'Generate from assets',
    '由资产生成 locres': 'Generate locres from assets',
    '扫描 .uasset / .uexp / .umap 中的 FText，生成可用的 locres，可作为模板。':
      'Scans FText in .uasset / .uexp / .umap files and writes a usable locres that can serve as a template.',
    '例如 Content\\GameCode\\UI': 'e.g. Content\\GameCode\\UI',
    '留空 = 目录下 build.locres': 'Empty = build.locres in that folder',
    '模板 locres（可选）': 'Template locres (optional)',
    '留空 = 用内置头': 'Empty = built-in header',
    '文本定位': 'Locate text',
    '定位文本（区分 key 与裸串）': 'Locate text (key vs. raw string)',
    '扫描资产中的 FText：A 组含 key，可由 locres 覆盖；B 组为裸串，仅能修改 uexp。输出文件路径与偏移。':
      'Scans FText in assets: group A carries a key and can be overridden by locres; group B is a raw string that needs a uexp edit. Outputs file path and offset.',
    '留空 = 目录下 report.csv': 'Empty = report.csv in that folder',
    '字体转 ufont': 'Font to ufont',
    '字体转 .ufont': 'Convert font to .ufont',
    'UE4 的 .ufont 为裸字体字节，选择 ttf / otf 即可生成，输出文件名可自定义。':
      'A UE4 .ufont is raw font bytes; pick a ttf / otf and it is generated, with a custom output name.',
    '字体文件': 'Font file',
    '拖 .ttf / .otf 进来': 'Drop a .ttf / .otf here',
    '输出文件名': 'Output name',
    '留空 = 用字体名，自动补 .ufont': 'Empty = font name with .ufont appended',

    /* ---- 绕签名 ---- */
    '免签名': 'Signature-free',
    '生成代理 DLL，为游戏命令行追加 -fileopenlog 等参数，使未签名 PAK 可被加载。':
      'Builds a proxy DLL that appends -fileopenlog and similar switches to the game command line so unsigned PAKs load.',
    '游戏 Shipping 路径（.exe）': 'Game Shipping path (.exe)',
    '列出可劫持 DLL': 'List hijackable DLLs',
    '读取 EXE 导入表，按导出数量升序列出可用作代理宿主的系统 DLL。':
      'Reads the EXE import table and lists system DLLs usable as proxy hosts, fewest exports first.',
    '一键装': 'One-click',
    '一键生成并部署': 'Build and deploy in one click',
    '自动选择宿主，编译代理 DLL 并部署至 EXE 同级目录。':
      'Picks a host automatically, compiles the proxy DLL and deploys it next to the EXE.',
    '注入参数': 'Injected arguments',
    '记录引擎打开的 pak/sig/locres': 'Log pak/sig/locres the engine opens',
    '指定宿主': 'Pick host',
    '指定宿主生成': 'Build with a chosen host',
    '指定宿主 DLL 进行生成；勾选「部署」可直接写入 EXE 目录。':
      'Builds with the chosen host DLL; tick Deploy to write it into the EXE folder.',
    '宿主 DLL': 'Host DLL',
    '编译后直接部署': 'Deploy after build',
    '卸载并还原': 'Uninstall and restore',
    '删除代理 DLL，并还原已备份的原版 DLL。':
      'Removes the proxy DLL and restores the backed-up original.',
    '清理残留': 'Clean leftovers',
    '清理临时文件与残留': 'Clean temp files and leftovers',
    '删除 raosig 临时编译目录；指定游戏目录时一并清理已部署的代理 DLL。':
      "Deletes raosig's temp build folder; with a game folder given, deployed proxy DLLs are removed too.",

    /* ---- 解包 ---- */
    '拆 pak': 'Unpack pak',
    '普通 PAK 使用 repak 解包，IoStore（.utoc/.ucas）使用 retoc 解包；加密包需填写 AES 密钥。':
      'Plain PAKs unpack with repak; IoStore (.utoc/.ucas) unpacks with retoc; encrypted ones need an AES key.',
    '游戏目录（只用来找 pak，可留空）': 'Game folder (only used to find paks; optional)',
    '普通 PAK': 'Plain PAK',
    '使用 repak 解包：载入后显示头信息与文件清单，开始后按挂载点 ../../../ 释放到目标目录。':
      'Unpacks with repak: shows header and file list on load, then extracts under mount point ../../../ into the target folder.',
    '拖一个 .pak 进来': 'Drop a .pak here',
    '留空 = pak 同目录 <同名>_unpack': 'Empty = <name>_unpack next to the pak',
    '32 位 hex，加密包才需要': '32-hex; only needed for encrypted paks',
    '使用 retoc unpack 解包 .utoc（需同目录下的同名 .ucas）；加密容器需填写 AES 密钥。':
      'Unpacks .utoc with retoc unpack (a matching .ucas must sit beside it); encrypted containers need an AES key.',
    'UTOC 容器': 'UTOC container',
    '拖一个 .utoc 进来（同目录需有 .ucas）': 'Drop a .utoc here (.ucas must be alongside)',
    '留空 = 同目录 <同名>_unpack': 'Empty = <name>_unpack in the same folder',

    /* ---- 打包 ---- */
    'repak pack / 挂载点': 'repak pack / mount point',
    '重新打包': 'Repack',
    '普通 PAK 使用 repak 打包（V8B / V11），IoStore 使用 retoc to-zen 打包；加密包需填写 AES 密钥。':
      'Plain PAKs pack with repak (V8B / V11); IoStore packs with retoc to-zen; encrypted ones need an AES key.',
    '使用 repak 打包：输入目录的顶层即挂载点下的内容，默认前缀 ../../../。':
      "Packs with repak: the input folder's top level becomes the mount point content; default prefix ../../../.",
    '要打包的文件夹': 'Folder to pack',
    '留空 = 目录同级 <目录名>.pak': 'Empty = <folder name>.pak alongside',
    'Zlib / Oodle / 留空不压': 'Zlib / Oodle / empty = no compression',
    '使用 retoc to-zen 将已 cook 的目录打包为 .utoc / .ucas / .pak；引擎版本按 UE4_26、UE5_3 填写。':
      'Packs a cooked folder into .utoc / .ucas / .pak with retoc to-zen; set the engine version such as UE4_26 or UE5_3.',
    '要打包的文件夹（含 .uasset/.uexp/.ubulk）':
      'Folder to pack (with .uasset/.uexp/.ubulk)',
    '输出 UTOC': 'Output UTOC',
    '留空 = 目录同级 <目录名>.utoc': 'Empty = <folder name>.utoc alongside',
    '引擎版本': 'Engine version',
    '32 位 hex，要加密才填': '32-hex; fill in to encrypt',

    /* ---- 工具面板 ---- */
    '启动 UAssetGUI（v1.1.0），查看与导出 .uasset 资产及属性树；下方列出资产路径内的 UE 资产，并可直接查看 .locres 内容。':
      'Launches UAssetGUI (v1.1.0) to inspect and export .uasset assets and property trees; the list below shows UE assets under the asset path, and .locres contents can be viewed directly.',
    '启动 UAssetGUI': 'Launch UAssetGUI',
    '点击「开始」启动 UAssetGUI。': 'Press Start to launch UAssetGUI.',
    '启动 FModel，浏览 PAK / IoStore 容器，导出模型、贴图与数据表。':
      'Launches FModel to browse PAK / IoStore containers and export models, textures and data tables.',
    '启动 FModel': 'Launch FModel',
    '点击「开始」启动 FModel。': 'Press Start to launch FModel.',
    '启动 jmap_dumper，注入后采集 UE 反射信息，生成 .jmap / .usmap 映射。':
      'Launches jmap_dumper; after injection it collects UE reflection data and writes .jmap / .usmap mappings.',
    '启动 jmap_dumper': 'Launch jmap_dumper',
    '点击「开始」启动 jmap_dumper。': 'Press Start to launch jmap_dumper.',

    /* ---- 仓库 ---- */
    'GitHub · 一键装新工具': 'GitHub · install new tools',
    '装工具': 'Install tools',
    '后续从 GitHub 拉取工具清单，安装至 tools\\ 并自动生成入口。':
      'Fetches the tool list from GitHub, installs into tools\\ and creates entries automatically.'
  });

  window.I18N.retranslate();
})();
/* --- extended UI copy --- */
if (window.I18N && window.I18N.extend) {
  window.I18N.extend({
    "AES Key 提取": "AES Key Extraction",
    "LOCRES 查看：选中 .locres 即可查看 key / source / target 三列与条目总数": "LOCRES viewer: pick a .locres to inspect the key / source / target columns and the total entry count",
    "Mappings 文件夹：设置里指定一个目录，UAssetGUI 与 FModel 面板可快速切换其中的 .usmap（含子目录，最多 3 层）": "Mappings folder: point Settings at one directory, then the UAssetGUI and FModel panels can switch between its .usmap files (subfolders included, up to 3 levels)",
    "Mod 制作：资源解包核查、贴图与文本替换、重新打包与加载验证": "Mod making: inspect unpacked assets, swap textures and text, repack and verify by loading",
    "locres 汉化": "locres localization",
    "pak 解包 / 打包": "pak unpack / pack",
    "使用": "Usage",
    "使用即表示已阅读并同意上述条款；如不同意，请立即停止使用并删除本程序。": "Using this tool means you have read and accepted the terms above; if you disagree, stop using it and delete the program.",
    "使用本工具修改、打包、注入或以其他方式处理文件所产生的全部后果，由使用者自行承担。": "You are solely responsible for every consequence of modifying, packing, injecting or otherwise processing files with this tool.",
    "刷新列表": "Refresh list",
    "加载中…": "Loading…",
    "卸载": "Uninstall",
    "可直接 Ctrl+V 粘贴路径，或点「查找目录」手动选择": "Paste a path with Ctrl+V, or click Browse to pick one",
    "后续从 GitHub 拉取工具清单，安装至 tools\\ 并自动生成入口。": "Tool catalogs will be pulled from GitHub, installed into tools\\ with entries generated automatically.",
    "在进程内存转储中检索明文密钥；需先将转储放入工具目录的 mem\\。": "Searches a process memory dump for plaintext keys; put the dump into mem\\ under the tool folder first.",
    "填写仓库后可用于检查更新与下载新版本；留空则只做本地版本展示。支持 owner/repo 或完整地址。": "With a repository filled in, update checks and downloads work; leave it empty to show the local version only. Accepts owner/repo or a full URL.",
    "子目录，后续通过仓库安装的工具同样安装至此。": "subfolder; tools installed from the repository land here too.",
    "工具箱根目录。全部内置工具与运行依赖位于其下的": "Toolbox root. All bundled tools and runtime dependencies live in the",
    "字体替换": "Font replacement",
    "展开 AES KEY": "Expand AES KEY",
    "工具箱": "Toolbox",
    "打开 AESKEY.txt": "Open AESKEY.txt",
    "打开更新日志": "Open changelog",
    "扫描代码立即数": "Scan code immediates",
    "扫描可执行文件": "Scan executable",
    "文案规范：每个功能的标题与说明统一为「做什么 + 关键参数与产物」的表述": "Wording: every feature title and description follows the same \"what it does + key parameters + outputs\" pattern",
    "新版本可用": "New version available",
    "最大化": "Maximize",
    "最小化": "Minimize",
    "本地化流程：文本抽取 → 翻译 → locres 重建 → 补丁 pak 打包 → 未签名包加载验证": "Localization flow: extract text → translate → rebuild locres → build patch pak → verify unsigned pak loading",
    "本工具仅提供调用与整合能力，不包含也不主张任何第三方工具的所有权。FModel、UAssetGUI、repak、retoc、jmap_dumper、Dumper-7、UnrealLocres 等均由各自作者开发并保留全部权利，其版权与许可归属原作者；使用前请自行阅读并遵守对应项目的许可条款。": "This tool only provides calling and integration. It does not contain or claim ownership of any third-party tool. FModel, UAssetGUI, repak, retoc, jmap_dumper, Dumper-7 and UnrealLocres are developed by their respective authors, who retain all rights; read and follow each project's license before use.",
    "本工具仅用于个人学习与研究，面向本人持有合法授权的游戏或工程文件。": "This tool is for personal study and research only, on games or project files you are legally authorized to use.",
    "查看": "View",
    "界面统一：深浅两套主题均为黑白配色，输入框、下拉、复选框与状态徽标采用同一套尺寸与描边": "Consistent UI: both dark and light themes are monochrome, and inputs, selects, checkboxes and status badges share one sizing and stroke set",
    "程序按「现状」提供，不对功能完整性、数据安全或由此导致的存档损坏、封号等损失作任何担保。": "The program is provided as-is, with no warranty for completeness, data safety, save corruption or account bans.",
    "请勿将本工具用于商业分发、破解传播或任何侵犯他人著作权、违反当地法律法规的行为。": "Do not use this tool for commercial distribution, piracy, or any act that infringes copyright or breaks local law.",
    "资产目录": "Asset folder",
    "资产路径": "Asset path",
    "资产路径：资产查看内直接填写解包后的 Content 目录，下方列出其中的 uasset / umap / uexp 并给出计数": "Asset path: fill in the unpacked Content directory on the Assets panel; uasset / umap / uexp files are listed below with counts",
    "路径历史：游戏目录 / 资产目录 / 资产路径输入框记录用过的路径，可从下拉中直接选回": "Path history: the game, asset folder and asset path inputs remember past paths, pick one straight from the dropdown",
    "输出": "Output",
    "选择 .locres": "Pick .locres",
    "选择一个 .locres 文件": "Pick a .locres file",
    "面向 UE4/UE5 工程的资源与本地化处理工具集。单文件可执行，内置密钥提取、pak 编解码、locres 本地化、文本定位、字体替换与签名绕过能力。": "A resource and localization toolkit for UE4/UE5 projects. One executable with key extraction, pak codec, locres localization, text locating, font replacement and signature bypass.",
  });
}
/* --- remaining UI copy --- */
if (window.I18N && window.I18N.extend) {
  window.I18N.extend({
    "UAssetGUI 与 FModel 面板的映射下拉列表将从该目录（含子目录，最多 3 层）检索 .usmap 文件。": "The mapping dropdowns in the UAssetGUI and FModel panels read .usmap files from this folder (subfolders included, up to 3 levels).",
    "dump 目录（空 = <游戏目录>\\mem）": "Dump folder (empty = <game folder>\\mem)",
    "ghp_… 仅用于提高接口配额 / 访问私有仓库": "ghp_… only raises the API rate limit / accesses private repositories",
    "locres 文件": "locres file",
    "后续从 GitHub 拉取工具清单，安装至 tools\\ 并自动生成入口。": "Tool catalogs will be pulled from GitHub, installed into tools\\ with entries generated automatically.",
    "在进程内存转储中检索明文密钥；需先将转储放入工具目录的 mem\\。": "Searches a process memory dump for plaintext keys; put the dump into mem\\ under the tool folder first.",
  });
}
if (window.I18N && window.I18N.extend) {
  window.I18N.extend({
    "TI工具箱": "TI Toolbox",
  });
}
