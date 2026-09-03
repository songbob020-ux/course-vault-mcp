# 从登录到 Obsidian 的工作流

这份文档描述完整的人机工作流，而不是声称所有步骤都由 Course Vault MCP 执行。v0.1 只负责 collector 台账导入、受限字幕读取、草稿 staging、校验、审计和 Obsidian 预览；浏览器登录与采集由外部组件完成，人工批准与真正发布只允许本地 CLI。

## 角色与信任边界

| 角色 | 负责 | 不负责 |
|---|---|---|
| 用户 | 授权范围、Chrome 登录、来源复核、批准和发布确认 | 不把凭据交给模型 |
| Chrome 扩展 | 在已登录页面读取正常暴露的字幕 | 不导出 Cookie，不绕过访问控制 |
| localhost collector | 目标队列、采集、临时缓存、hash 台账 | 不生成课程结论 |
| MCP Host/模型 | 分页读取有限片段、生成原创草稿、报告不确定性 | 不自批草稿，不写入 Vault |
| Course Vault MCP | 状态、路径、内容边界、hash、预览和审计 | 不登录、不控制扩展、不判断策略有效性 |
| 本地 CLI | 记录人工批准、确定性校验、最终 commit | 不替用户完成来源判断 |

## 0. 配置授权范围

- 指定课程站精确 HTTPS hostname、私人课程项目、collector、临时缓存和 Vault 子目录。
- 用户自行确认账号有权访问，并确认网站条款允许其个人学习整理。
- 不配置通用 URL 抓取，不接受 Cookie 文件、storage state 或浏览器 profile。
- Vault 根目录必须已经存在；MCP 直接写 Markdown，不要求 Obsidian REST 插件。
- 配置文件和 state 目录属于私人运行数据，不进 Git。

## 1. 人工登录

1. 用户在自己的 Chrome 打开会员登录页。
2. 用户亲自输入账号、密码和 MFA。
3. 扩展只复用当前标签页会话，不读取或导出 Cookie。
4. 用户确认页面确实显示有权访问的课程，而不是仅凭地址栏判断登录成功。
5. 登录失效时队列进入 `auth_required` 并停止；MCP 只报告状态，用户回到 Chrome 重新认证。

v0.1 不包含登录自动化，也不能从 MCP 内点击扩展按钮。登录完成不代表 collector 已连接或已经开始采集。

## 2. 外部 collector 采集

1. 单独启动兼容的 localhost collector，并确认其 health endpoint 正常。
2. 在 Chrome 安装、启用并连接兼容扩展。
3. 扩展从 collector 取得精确允许的课程目标。
4. 每次只加载一课，识别允许的播放器和正常暴露的字幕轨。
5. collector 验证课程 ID、来源域名、字幕域名、格式、大小和数量。
6. 原字幕及 2–3 分钟语义段只写配置的临时目录。
7. 项目台账只保存语言、时间范围、cue 数、SHA-256 和状态。

`captured` 只表示采集证据存在，不表示视频已看懂。collector 的安装、start/pause、页面导航、重试和版本升级不由本仓库提供；兼容组件必须单独记录这些步骤。

## 3. MCP 导入

1. `doctor` 报告配置、collector 连接和缓存一致性。它会初始化 state 目录和 SQLite，不是纯只读命令。
2. `refresh_collector` 将元数据和队列状态幂等导入 SQLite。
3. `list_lessons` 和 `next_action` 用于选择下一课，不推进状态。
4. 如果 collector 不可达但 manifest 完整，旧元数据仍可能可读；这不代表可以继续采集。
5. 如果 manifest 宣称 cache 可用但语义段缺失，必须报告 drift，不得把 hash 台账当成可复核正文。

旧 collector 状态需降级解释：legacy `reviewed` 最高映射为 MCP `captured`。只有存在 MCP draft、来源定位和本地人工批准记录后，才能进入 MCP 的 `reviewed`。

## 4. 分页读取与归纳

`get_review_packet` 按单课、单语言、限长分页：

```text
get_review_packet(lesson_id, cursor=null, language=null, max_chars=...)
```

返回内容包括：

- `available_languages`：可选字幕语言；
- 当前页的语义段和时间范围；
- `next_cursor`：下一页游标，末页为 `null`；
- 顶层 `characters`：当前页返回字符数；
- `packet_sha256` 与 `track_sha256`：当前页和所选字幕轨 hash；
- `coverage`：当前页返回分段数、总分段数、遍历位置、时间范围和是否完成。

MCP Host 必须：

1. 先选定一个语言，不把平行翻译轨混在同一个字符预算中；
2. 顺序读取到 `next_cursor=null`，不得只读第一页后声称完成一课；
3. 保存覆盖回执，并明确字幕缺失、截断或语言质量问题；
4. 用 `course_to_card` prompt 生成原创归纳；
5. 调用 `save_lesson_draft` 写入 Vault 外的 staging 目录，并显式设置 `source_language`、`transcript_coverage_complete` 与 `visual_evidence`。

课程卡至少包含：

- 一句话结论；
- 核心概念；
- 决策规则候选；
- 反例、例外和失效；
- 待验证问题；
- 课程 ID 与时间点；
- `source_language`；
- `transcript_coverage: complete|incomplete`；
- `visual_evidence: missing|reviewed|not_applicable`；
- 课程事实、系统代理、人工判断和研究假设的边界。

当草稿声称 `transcript_coverage_complete=true` 时，服务要求数据库已有相同 source hash、语言及对应 `track_sha256` 从 `0:0` 连续连接到末页的 cursor 回执链。该检查证明接口覆盖，不证明 Host 正确理解了每页内容。

v0.1 不向 MCP 暴露视频画面或关键帧。`visual_evidence` 是人工声明，不是自动视觉核验。字幕完整读取仍不能证明图表、幻灯片、手势或屏幕标注已被理解；依赖画面的结论必须保持 `visual_evidence: missing`。

## 5. 人工复核与本地批准

1. 用户或合格复核者打开原课程，对照课程 ID 和时间点检查摘要。
2. 对涉及图表的结论检查原画面，并更新 `visual_evidence`。
3. 修正遗漏、误解和过度推断；不要直接修改 content-addressed staging 文件，应让 MCP 保存一个新 draft，或修改私人旧卡后重新执行 legacy import。
4. 用户完成来源复核后，在本地终端执行 `approve LESSON --reviewer-note TEXT --confirm-source-check`，记录批准和 reviewer note。
5. MCP Host 不拥有批准工具，不能自行把 `ai-draft` 升级为课程事实。

保存或导入新 draft 会产生新 hash，并使旧批准失效。CLI 中的批准动作仍只是“用户在本机明确执行”的审计证据，不是第三方身份认证。团队场景应另外记录复核者身份和审核规范。

审核后发现问题时，用户运行 `request-revision LESSON --reason TEXT`，将 `reviewed`、`validated` 或 `synced` 退回 `drafted` 并撤销旧批准；随后保存新 draft，再重新复核、批准和校验。

## 6. 确定性校验

本地 CLI 对已批准草稿执行 `validate`，检查：

- 内容不是空白且不超尺寸；
- 未出现明显 WEBVTT、媒体字节或 credential 模式；
- draft 位于 staging 允许目录；
- draft SHA-256 未在保存后改变；
- 至少存在来源定位；
- 当前 draft 与 source hash 仍和批准记录一致。

每次 `get_review_packet` 会写 `source_reads` 审计；完整 coverage 声明必须有同 source hash、语言及对应 `track_sha256` 从第一页到末页的连续 cursor 回执链。上述确定性校验不是事实正确性证明，也不是完善的秘密扫描；来源定位格式与 hash 正确不自动证明时间点内容正确。

## 7. Obsidian 预览与发布

1. MCP Host 只能调用 preview 工具，返回目标路径、是否已存在、写前/写后 hash、字节数和是否变化。
2. 用户检查 preview 和最终草稿；MCP Host 不能 commit。
3. 新文件经用户确认后，由用户在本地 CLI 执行 `sync LESSON --commit --confirm-publish`。
4. v0.1 遇到已有且内容不同的文件时返回 `VAULT_CONFLICT`，不允许自动覆盖；用户在 Obsidian 中人工比较和合并。
5. 内容完全相同时不重复写入，但仍核对 SHA-256。
6. 新文件先在目标目录写入并 `fsync` 临时文件，再以拒绝覆盖的原子 hard-link 发布；写后重读，只有 SHA-256 一致才把状态改为 `synced`。

如果 Obsidian 已有同名内容，应换一个目标、保留 revision 文件或人工合并，不要为了绕过冲突而删除原笔记。

## 8. 缓存清理与停用

v0.1 刻意不提供 MCP 删除工具。现有 collector 的清理命令只能在以下证据齐全后由用户在本机执行：

```text
source reviewed
  + deterministic validation passed
  + Vault published
  + Vault bytes/hash verified
  = eligible for cache purge
```

清理不可恢复；如需重新审核只能定向重新采集。停止使用时：

1. 断开 MCP Host；stdio MCP 会随 Host 断开；另行停止 collector 进程；
2. 在 Chrome 禁用或移除课程采集扩展；
3. 不再需要时再按证据门人工清理临时字幕缓存；
4. 保留或一致性备份 SQLite 台账、原创草稿和发布回执；
5. 如需 Vault 历史版本，使用 Obsidian/文件系统自己的备份方案；v0.1 因禁止覆盖而不生成覆盖前备份。

## 9. 旧卡迁移

- 先用 `import-legacy LESSON` 查看旧原创课程卡的导入预览，再用 `import-legacy LESSON --commit` 复制到 content-addressed staging。
- 旧状态不得直接越过本工作流的人工复核门。
- 临时语义段仍在时，可分页完成定向来源复核。
- 临时语义段已清理时，只在确有复核需要的课程上定向重采，不默认全量重采，也不声称“全量无需重采”。
- source hash 变化时先停在 `needs_attention`；唯一例外是可验证的旧集合指纹迁移：课程仍在 `discovered`/`captured` 且没有 artifact、source refs 或有效批准时，可重键为新的语言映射指纹并记录事件，旧读取链因 hash 不同自动失效。其他情况由用户核对定向重采结果后运行 `acknowledge-source-change LESSON --note TEXT --confirm-recapture`，才能回到 `captured` 并重新走草稿链。
- 旧卡完成本地批准、validation 和 preview 后，才由用户选择是否发布到新的 Vault 子目录。

具体兼容结构和迁移验收见 [BROOKS_INTEGRATION.md](BROOKS_INTEGRATION.md)。

## 10. 跨课程知识整理（计划中的 v0.2）

建议状态：

```text
课程卡
  → 主题证据卡
  → 金字塔节点
  → 规则候选
  → COURSE_FACT / SYSTEM_PROXY / HYPOTHESIS / PARAMETER
  → 独立图表复核与数据验证
```

v0.1 尚未自动执行这部分。课程权威不能替代盈利验证；任何交易规则仍需成本后回测、样本外、模拟盘和确定性风险控制。
