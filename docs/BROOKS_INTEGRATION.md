# Brooks legacy collector 接入与迁移

本页说明如何把既有 Brooks 私人课程 workspace 接入 Course Vault MCP。它不包含会员账号、真实 manifest、字幕、课程卡正文、个人路径或扩展安装包；这些数据继续留在私人 workspace。

Course Vault MCP 不属于 Brooks Trading Course，也不代表课程方。用户必须自行确认有权访问和整理相关材料，并遵守网站条款。代码仓库不得用于分发会员内容。

## 1. 接入范围

v0.1 只适配既有 collector 的本地合约：

```text
<private-project>/collector/config/targets.prototype.json
<private-project>/collector/data/manifest.json
<private-project>/collector/data/review-queue.json
<private-cache>/<lesson-id>/*.segments.json
<private-cache>/<lesson-id>/<language>.vtt       # 仅用于本地完整性重验
<private-project>/lessons/<lesson-id>.md       # 可选旧原创卡
```

adapter 只应读取：

- 课程 ID、标题和去查询参数后的允许域名 URL；
- 队列状态和脱敏错误；
- 字幕语言、时间范围、cue/segment 数及 hash；
- 原 VTT 的本地流式 hash/分段校验结果，以及向 MCP 返回的限长临时语义段；
- 用户原创旧卡的路径/hash，用于显式迁移。

它不应读取或持久化：

- Chrome Cookie、storage state、profile、密码、MFA 或认证头；
- 视频、DRM 媒体、签名媒体 URL；
- 未经限制的完整网页或任意文件；
- 会员字幕到 Git 或 Obsidian。

原 VTT 只在本地内存中用于重算 manifest track hash 并确定性核对分段，不写入 state、日志、异常或工具响应。若原 VTT 已清理，即使 `*.segments.json` 仍存在，也必须定向重采后才能继续来源复核。

## 2. 外部组件不是本仓库的一部分

旧流程的 Chrome 扩展和 localhost collector 必须单独安装、启动和升级。Course Vault MCP 不会：

- 自动打开登录页或输入账号；
- 点击扩展的开始/暂停；
- 自动跨课程页面导航；
- 修复 `auth_required`；
- 下载视频；
- 替用户决定是否重新采集。

私人运维记录应固定扩展版本、collector 版本、允许域名、端口、启动命令和恢复步骤，但不能把真实凭据或会员内容复制到公共仓库。

## 3. 迁移前只读盘点

不要先复制或改写旧卡。先记录：

```bash
.venv/bin/course-vault --config /absolute/path/course-vault.toml audit-legacy
```

- targets 总数及 lesson ID 唯一性；
- manifest、queue 和 targets 的 ID 差集；
- 各状态数量；
- 有 source hash 的课程数；
- manifest 宣称 cache available、但 segments 实际缺失的课程数；
- 旧原创课程卡存在数；
- collector 当前是否可达；
- Obsidian 目标路径是否已存在同名文件。

盘点结果只能描述“台账、缓存和旧卡现在是什么状态”，不能由 hash 推断字幕正文仍存在，也不能由旧 `reviewed` 推断已经完成 MCP 人工审核。

## 4. 状态降级映射

legacy 状态和 MCP 状态使用不同证据标准，迁移时采用保守映射：

| legacy 状态 | MCP 导入上限 | 原因 |
|---|---|---|
| `pending` | `discovered` | 只知道目标存在 |
| `captured` | `captured` | 有采集台账，但尚无 MCP 草稿/批准 |
| `reviewed` | `captured` | 旧审核不包含 MCP coverage、draft artifact 与本地批准证据 |
| `auth_required` | `auth_required` | 必须由用户回到 Chrome 登录 |
| `failed` | `failed` | 保留脱敏失败状态，不自动循环 |
| `needs_attention` | `needs_attention` | 等待人工检查 |

旧 `reviewed_at` 可作为来源元数据保留，但不能直接推动 MCP 状态到 `reviewed`。

早期开发版曾使用不含语言映射的 source fingerprint。首次刷新时，系统只会对仍处于 `discovered`/`captured` 且没有 artifact、source ref 或有效批准的课程安全换算新 fingerprint，并记录一次保持原状态的 migration event；任何已有下游语义证据的课程都会停在 `needs_attention`，不能借算法升级绕过复核。

## 5. 根据源材料可用性分层处理

### A. 临时语义段仍完整

1. 选择语言；
2. 用 cursor 逐页读取到 `next_cursor=null`；
3. 记录 coverage；
4. 生成草稿，或先用 `import-legacy LESSON` 预览并以 `--commit` 导入 staging；
5. 用户按时间点和必要画面复核；
6. 本地 CLI 批准、校验、preview 和 commit。

### B. 有旧原创卡和 source hash，但语义段已清理

- 保留旧卡和台账，不需要为了“迁移数据”立即全量重采；
- 先用 `import-legacy LESSON` 预览，再用 `import-legacy LESSON --commit` 显式导入 staging；不能直接复制到新 Vault 后标为 reviewed；旧卡原样导入时可能没有新模板的结构化 coverage/visual frontmatter，状态以本地 ledger 为准；
- 如果用户要重新确认某条结论，或者要把该课升级为 MCP reviewed，只对相应课程定向重采；
- 新采 source hash 与旧 hash 不同，必须按新来源重新复核，不能沿用旧批准。
- 已有 artifact、source refs 或有效批准时，source hash 变化会进入 `needs_attention`；定向重采并人工核对后，用 `acknowledge-source-change LESSON --note TEXT --confirm-recapture` 回到 `captured`。
- 若差异仅来自已知旧集合指纹算法，且课程仍为 `discovered`/`captured`、没有上述下游证据，首次刷新可安全重键并记录事件；旧 `source_reads` 因新 hash 不匹配而失效。

### C. 只有 manifest/hash，没有旧卡和语义段

- 只能导入发现/采集元数据；
- 不能生成完整课程卡；
- 需要该课时再定向重采。

因此，正确表述不是“旧课程全部无需重采”，也不是“必须把所有课程重采一遍”，而是：

> 旧原创卡和 hash 台账可以迁移；来源复核按需要定向重采，以当前可用分段和目标质量门决定。

## 6. 三课试点

在批量迁移前，选择三种情况各一课：

1. segments 完整且有旧卡；
2. 有旧卡但 segments 缺失；
3. 曾失败、需要登录或需要人工注意。

每课检查：

- 课程 ID、标题、允许域名和 source hash；
- legacy 状态是否安全降级；
- 语言选择、分页顺序和 coverage；
- 旧卡是否只进入 staging；
- 课程时间点和 `visual_evidence`；
- 本地批准记录；
- Obsidian preview 路径和冲突 hash；
- commit 后的 SHA-256 receipt；
- Git 没有发现私人 artifacts。

三课全部通过后才扩到较大批次。批次之间继续保留可恢复 checkpoint，不自动跨过人工批准门。

## 7. Brooks 内容的特殊质量要求

Brooks 课程大量结论依赖图表上下文。v0.1 只能核对字幕，不向 MCP 暴露视频画面，因此：

- “讲师说了什么”可由字幕时间点支持；
- “图中哪根 K 线、哪条通道或区间边界支持该结论”必须人工回看；
- 缺视觉证据时标记 `visual_evidence: missing`，不能自动升级成 `COURSE_FACT`；
- 课程中的 `often`、`usually` 等词不能被模型改写为固定胜率；
- 课程事实、系统代理、研究假设和参数必须分开。

课程卡同步完成不代表策略在 BTC 或其他市场盈利。策略应用仍需无泄漏标签、成本后回测、样本外、模拟盘和确定性风控。

## 8. Obsidian 目标

建议把 MCP 发布到专用子目录，不覆盖原私人课程 workspace：

```text
<Vault>/Courses/Brooks/
  lessons/
  topics/       # v0.2 计划
  rules/        # v0.2 计划
  indexes/      # v0.2 计划
```

v0.1 只保证单课 Markdown 的 staging、preview 和安全 commit，不自动建立主题卡、金字塔、Canvas 或策略规则图。旧 Vault 中已有同名且不同内容的笔记时会返回 `VAULT_CONFLICT`；v0.1 不提供自动覆盖，必须人工比较和合并。

## 9. 可对外报告的状态用语

| 证据 | 可以说 | 不可以说 |
|---|---|---|
| targets/manifest 已导入 | “已索引 N 课” | “已提取 N 课内容” |
| source hash 存在 | “已有采集 hash 台账” | “字幕仍可读取” |
| coverage complete | “指定字幕轨已完整分页读取” | “视频画面已完整理解” |
| staging draft | “AI 草稿已生成” | “课程事实已确认” |
| 本地批准 + validation | “该课程卡已按记录完成来源复核” | “策略已验证有效” |
| Vault receipt verified | “知识卡已安全发布到 Vault” | “课程体系/交易系统已完成” |

## 10. 私人与公共仓库边界

公共 Course Vault MCP 仓库只保存代码、空配置、模板、Schema、合成测试和通用文档。以下内容即使在 private GitHub repository 也不应提交：

- 真实 targets、manifest、queue 和 SQLite；
- 课程字幕、视频、关键帧、附件和签名 URL；
- 旧课程卡全文或完整私人 Obsidian Vault；
- 本机绝对路径、账号或认证材料；
- collector 运行日志和故障截图中可能出现的会员信息。

发布前按 [GITHUB_RELEASE.md](GITHUB_RELEASE.md) 运行测试、公开导出审计和人工 staged diff 检查。
