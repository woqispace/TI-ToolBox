# TI 工具箱

UE4 / UE5 资源与本地化处理工具箱：单文件桌面程序，把「找 key → 解包 → 文本 → locres → 打包 → 验签」这条链路收进一个窗口。

## 功能

- **AES 提取**：exe / 代码立即数 / 内存 / 文本 / DPAPI 五路挖 pak 密钥，命中即用 pak 索引 SHA-1 校验
- **文本**：locres 导出 / 导入 / 生成 / 打 pak，uasset 文本定位（A/B 分组），导出 key 清单，字体转 ufont
- **绕签名**：生成代理 DLL 注入 `-fileopenlog` 等参数，让未签名补丁包能被引擎加载
- **解包 / 打包**：普通 pak 走 repak，IoStore（.utoc）走 retoc
- **资产查看**：填 Content 目录列出 uasset / umap / uexp 并统计；内置 LOCRES 查看器
- **FMODEL / DUMP**：路径检测与一键启动；DUMP 支持枚举进程、注入 Dumper-7.dll
- **其他**：黑 / 白主题、路径历史、每工具独立参数、版本面板与 GitHub 检查更新

## 运行

直接运行 `TI工具箱.exe`（Windows 10/11，需 WebView2 运行时）。

## 从源码构建

```
pip install pywebview pyinstaller
pyinstaller --noconfirm --clean --noconsole --onefile --name "TI工具箱" ^
  --icon "ui\logo.ico" --add-data "ui;ui" --add-data "catalog.json;." ^
  --add-data "changelog.md;." --add-data "tools;tools" ^
  --hidden-import webview.platforms.edgechromium --collect-all webview desktop.py
```

## 目录

```
app.py           本地 HTTP API（任务执行 / 设置 / 文件选择）
desktop.py       pywebview 无边框窗口
catalog.json     工具与任务的声明式清单
changelog.md     更新日志（首页展示）
ui/              界面（index.html / app.js / style.css）
tools/           内置命令行工具与脚本
启动.bat         启动入口
```

## 免责声明

本工具仅用于个人学习与研究，面向本人持有合法授权的游戏或工程文件。使用本工具修改、打包、注入或以其他方式处理文件所产生的全部后果，由使用者自行承担。

请勿将本工具用于商业分发、破解传播或任何侵犯他人著作权、违反当地法律法规的行为。程序按「现状」提供，不对功能完整性、数据安全或由此导致的存档损坏、封号等损失作任何担保。

本工具仅提供调用与整合能力，不包含也不主张任何第三方工具的所有权。FModel、UAssetGUI、repak、retoc、jmap_dumper、Dumper-7、UnrealLocres 等均由各自作者开发并保留全部权利，版权与许可归属原作者；使用前请阅读并遵守对应项目的许可条款。

使用即表示已阅读并同意上述条款；如不同意，请立即停止使用并删除本程序。
