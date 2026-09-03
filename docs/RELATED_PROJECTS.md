# GitHub 调研与取舍

## 调研范围

本页是截至 **2026-09-03** 的非穷尽 GitHub 快照，不是“市场上绝对不存在同类项目”的证明。检索围绕以下能力组合进行：

```text
用户已授权的付费课程会话
→ 不导出密码/Cookie 的浏览器侧字幕采集
→ 分页覆盖与来源时间点
→ 人工质量门和状态审计
→ 原创课程卡
→ 冲突安全的 Obsidian 发布
```

使用的检索概念包括 MCP、course/video transcript、authenticated browser、Chrome extension、Obsidian、knowledge notes、source-linked、human review、atomic write 和 audit。项目会持续变化；采用前必须重新检查其最新 release、commit、许可证、安全公告和认证方式。

本次调研**未发现一个成熟的单一项目同时覆盖上述全部约束**。但已经存在多个接近的浏览器、视频归纳和 Obsidian 组件，因此 Course Vault MCP 的定位不是“别人都没有做过”，而是把最小权限认证边界、课程证据门和安全发布串成一条窄工作流。

## 能力矩阵

符号仅表示本次文档核对结果：`✓` 明确提供，`部分` 只覆盖相邻能力，`—` 不是该项目目标。

| 项目 | 已登录/受限来源 | 字幕/转录 | 视觉证据 | Obsidian 输出 | 课程来源/人工质量门 | 与本项目关系 |
|---|---:|---:|---:|---:|---:|---|
| Course Vault MCP | 部分：依赖外部受限扩展 | ✓ 分页读取既有缓存 | — v0.1 不暴露 | ✓ preview + CLI commit | ✓ 来源定位、人工批准、hash 审计 | 本项目 |
| [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) | — | — | — | — | — | MCP 协议与 Python 服务底座 |
| [microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp) | ✓ 可通过扩展连接现有标签页 | 部分：可操作网页 | ✓ 截图/浏览器状态 | — | — | 浏览器连接参考，权限面更宽 |
| [notoriouslab/browser-mcp-lite](https://github.com/notoriouslab/browser-mcp-lite) | ✓ Chrome 扩展 + 本机服务 | 部分：读取页面 | ✓ 截图 | — | — | 精简 MV3/localhost 配对参考 |
| [yanlingLabs/video-extract-mcp](https://github.com/yanlingLabs/video-extract-mcp) | 部分：可借浏览器 Cookie | ✓ 字幕/本地 ASR | ✓ 关键帧 | — | — | 强视频提取器，但凭据和媒体能力过宽 |
| [ipythonist/mcp-video](https://github.com/ipythonist/mcp-video) | 部分：通用视频 URL | ✓ | ✓ | — | — | 视觉+字幕参考，不是会员课证据工作流 |
| [adhikasp/mcp-youtube](https://github.com/adhikasp/mcp-youtube) | — 公开 YouTube | ✓ | — | — | — | 时间戳 transcript 工具形状参考 |
| [mohsinkhadim59/youtube-obsidian-mcp](https://github.com/mohsinkhadim59/youtube-obsidian-mcp) | — 公开 YouTube | ✓ | ✓ 截图 | ✓ | 部分：时间戳，无本项目状态门 | 接近的字幕/截图到 Vault 流程 |
| [trans93589/course-video-to-obsidian](https://github.com/trans93589/course-video-to-obsidian) | 部分：公开视频/本地媒体 | ✓ | 部分 | ✓ 笔记、Canvas、复习材料 | ✓ 强调证据链接；无会员会话边界 | 接近的课程知识化 UX 参考 |
| [drpwchen/lecture-to-notes](https://github.com/drpwchen/lecture-to-notes) | 本地录制材料 | ✓ 本地 ASR | ✓ 幻灯片/OCR/视觉信号 | ✓ Markdown Vault | 部分：同步查看与来源材料 | 视觉复核和学习界面参考 |
| [KIRVO-REPORTING/video-to-notes](https://github.com/KIRVO-REPORTING/video-to-notes) | 部分：公开视频/本地媒体 | ✓ | 部分 | ✓ | ✓ 时间戳归纳；无本项目人工状态门 | 安装、预检、进度 UX 参考 |
| [mwkloh/ytextract](https://github.com/mwkloh/ytextract) | — 公开 YouTube | ✓ | — | ✓ Obsidian 插件内 | — | Obsidian 内一体化体验参考 |
| [3011/obsidian-vault-mcp](https://github.com/3011/obsidian-vault-mcp) | — | — | — | ✓ | 部分：文件级安全/审计 | 安全 Vault 写入参考，权限更通用 |
| [dalager/obsidian-mcp](https://github.com/dalager/obsidian-mcp) | — | — | — | ✓ | — | 多 Vault/allowed paths 参考 |
| [cyanheads/obsidian-mcp-server](https://github.com/cyanheads/obsidian-mcp-server) | — | — | — | ✓ | 部分：只读/拒绝覆盖/精确 patch | Obsidian 语义与权限配置参考 |

仓库发布后可以为 `Course Vault MCP` 一行补上真实 GitHub URL；发布前不应放一个猜测的 owner/repository 地址。

## 采用的设计参考

### Official Python MCP SDK

- 仓库：[modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk)
- 借鉴：Python 原生 tools、resources、prompts；本地默认 stdio，部署才使用 Streamable HTTP。
- 采用前检查当前 v2 文档和 breaking changes；本项目依赖范围以 `pyproject.toml` 为准。

### Microsoft Playwright MCP

- 仓库：[microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp)
- 借鉴：通过 Chrome 扩展连接真实浏览器标签页和既有登录状态。
- 不直接采用：课程 MCP 不应暴露通用浏览器控制、任意 JavaScript 或 storage state；其授权面远大于本项目所需的字幕采集器。

### MCP Filesystem reference server

- 仓库：[modelcontextprotocol/servers/filesystem](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem)
- 借鉴：根目录和路径 allowlist。
- 本项目额外要求：只允许课程卡 Markdown、先 preview、拒绝覆盖已有不同内容、原子创建和 hash 回执；真正 commit 只在本地 CLI。

### Obsidian Vault MCP implementations

- [3011/obsidian-vault-mcp](https://github.com/3011/obsidian-vault-mcp)：原子写入、备份、审计、路径穿越与 symlink 测试值得借鉴。
- [dalager/obsidian-mcp](https://github.com/dalager/obsidian-mcp)：多 Vault 和 allowed paths 配置值得借鉴。
- [cyanheads/obsidian-mcp-server](https://github.com/cyanheads/obsidian-mcp-server)：默认拒绝覆盖、精确 patch、只读开关和权限配置值得借鉴。

通用 Vault MCP 的权限和功能通常大于课程卡发布所需范围。本项目 v0.1 不提供 delete、move、任意文件读取或 MCP commit，因此没有必要仅为写一类课程卡而引入全 Vault API。

### Browser / transcript / video-to-notes projects

- [notoriouslab/browser-mcp-lite](https://github.com/notoriouslab/browser-mcp-lite)：Chrome MV3 与本机服务配对的精简形态。
- [yanlingLabs/video-extract-mcp](https://github.com/yanlingLabs/video-extract-mcp)：URL 到字幕、ASR 和关键帧的工具接口。
- [adhikasp/mcp-youtube](https://github.com/adhikasp/mcp-youtube)：带时间戳 transcript 的简单工具形状。
- [mohsinkhadim59/youtube-obsidian-mcp](https://github.com/mohsinkhadim59/youtube-obsidian-mcp)：从公开视频字幕和截图直接生成 Obsidian 笔记。
- [trans93589/course-video-to-obsidian](https://github.com/trans93589/course-video-to-obsidian)：证据链接、Canvas 地图和复习材料。
- [drpwchen/lecture-to-notes](https://github.com/drpwchen/lecture-to-notes)：本地 ASR、幻灯片/OCR、同步查看和 Vault Markdown。
- [KIRVO-REPORTING/video-to-notes](https://github.com/KIRVO-REPORTING/video-to-notes)：本地优先安装、环境预检、时间戳摘要和多目标导出。
- [mwkloh/ytextract](https://github.com/mwkloh/ytextract)：在 Obsidian 内提取公开视频字幕并选择本地或云端模型摘要。

这些项目证明“视频到 Obsidian”本身并不新。Course Vault MCP 的差异应被限定为：针对已授权会员课程，在不接收凭据、不默认下载媒体的前提下，增加字幕覆盖回执、来源定位、人工批准、状态审计和最小权限发布。

通用 Cookie 借用、媒体下载和任意 URL 获取会扩大凭据、版权和 SSRF 风险；本项目坚持用户手工登录、精确域名 allowlist、正常字幕轨和 localhost collector。对于公开视频或用户自有本地视频，现有 video-to-notes 项目可能比本项目更合适。

### Obsidian Local REST API

- 仓库：[coddingtonbear/obsidian-local-rest-api](https://github.com/coddingtonbear/obsidian-local-rest-api)
- 可作为未来可选 adapter，支持 frontmatter/section patch。
- 安全公告 [GHSA-62gx-5q78-wrvx](https://github.com/coddingtonbear/obsidian-local-rest-api/security/advisories/GHSA-62gx-5q78-wrvx) 显示：`<= 4.1.2` 受路径穿越问题影响，`4.1.3` 修复。
- 若未来采用，必须要求 `>= 4.1.3`，同时继续执行本项目自己的 Vault allowlist、preview、拒绝覆盖策略和本地 CLI commit；不要只依赖上游版本声明。

## Build / borrow 决策

| 层 | 当前决定 | 原因 |
|---|---|---|
| MCP 协议 | borrow 官方 Python SDK | 标准协议不自行实现 |
| 浏览器连接 | 保留受限 collector/扩展 | 通用浏览器 MCP 权限过宽 |
| 字幕/视觉提取 | v0.1 只接入既有字幕缓存 | 避免默认媒体下载；视觉留给人工复核 |
| 课程知识化 | 自建窄 prompt、coverage、source refs 和状态门 | 通用摘要器缺少会员课证据语义 |
| Vault 发布 | 自建最小 VaultWriter | 只需一种受约束笔记写入，不需完整 Vault CRUD |
| 跨课程图谱 | 暂不实现 | 等单课证据和迁移语义稳定后再做 |

## 明确不采用

- 不通过 MCP 接收用户名、密码、MFA 或 Cookie 文件。
- 不把 yt-dlp 的浏览器 Cookie 导出作为默认认证方案。
- 不开放通用网页归档；付费站不得保存完整 HTML、视频或镜像。
- 不在 v0.1 引入向量数据库；Markdown、来源定位、hash 和审计台账先作为事实基线。
- 不复制许可证不兼容的项目代码进入 MIT 内核。

本仓库只借鉴公开设计思想，不应在没有逐项许可证核查、NOTICE 和来源说明的情况下复制第三方代码。
