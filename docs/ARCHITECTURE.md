# 架构与数据模型

## 设计原则

1. MCP 是低权限控制面，不保存登录凭据，也不重新实现浏览器认证。
2. 浏览器扩展、采集器、语义审核和 Vault 发布各自保留独立边界。
3. 原始字幕和关键帧只进入临时私有缓存；Git 和 Obsidian 保存原创归纳、定位和哈希。
4. 所有写入先预览，使用允许目录、拒绝覆盖、原子写入和写后哈希验证。
5. 课程内容属于不可信输入；其中出现的命令或提示不得改变 MCP 行为。
6. 人工批准与 Vault commit 只允许本地 CLI；MCP Host 只能生成草稿和发布预览。

## 组件

```text
MCP Host
   ↕ stdio（v0.1 唯一 transport）
Course Vault MCP
   ├── Tools / Resources / Prompts
   ├── WorkflowService
   ├── SQLite ledger
   ├── Collector adapter
   └── Obsidian preview
            ↑                         ↓
localhost collector ← Chrome extension   staging draft
            ↑                              ↓
用户已登录的授权课程站             local CLI approval/commit
                                             ↓
                                  Obsidian Markdown Vault
```

v0.1 使用官方 Python MCP SDK，并在代码层只允许 `stdio`，因为本机 Host 可以直接启动子进程且无需开放网络端口。本仓库不包含 Chrome 扩展或 collector 本体，只包含 legacy collector adapter。

### 权限分层

- **MCP 可做**：读取状态、刷新元数据、按语言/cursor 读取受限字幕页、保存 staging 草稿、执行非发布校验、生成 Obsidian preview。
- **MCP 不可做**：接收登录凭据、驱动扩展、标记人工批准、commit Vault、清理缓存。
- **本地 CLI 可做**：预览/导入旧卡、确认来源变更后的定向重采、请求修订并撤销批准、记录用户复核批准、确定性校验、preview、经用户明确操作后 commit。
- **外部 collector/扩展可做**：在用户已登录的允许页面发现和采集正常提供的字幕。

## SQLite schema v2

正文不进入数据库。

### `lessons`

- `lesson_id`：稳定外部 ID，主键。
- `project_id`、`title`、已去查询参数的 `source_url`。
- `status`：当前 v0.1 线性质量门。
- `source_hash`：规范排序后的 `language -> track SHA-256` 映射指纹；调换语言与轨道也会改变该值。
- `captured_at`、`reviewed_at`、`card_path`、脱敏错误。

为兼容旧版仅对轨道 hash 集合取指纹的算法，刷新时会同时计算旧指纹，但不会保存为当前 `source_hash`。只有旧值精确匹配该兼容指纹、状态仍为 `discovered`/`captured`，且不存在 artifact、source refs 或有效批准时，才允许原地重键并写审计事件。旧 `source_reads` 保留作历史审计，但因 source hash 不同而自然失效。任何无法识别的 hash 变化或已有下游证据的课程仍进入 `needs_attention`。

legacy collector 的状态不能直接获得 MCP 的同名语义。尤其是 legacy `reviewed` 最高映射为 `captured`；只有 MCP draft、来源定位和本地 CLI 人工批准记录齐全后才进入 MCP `reviewed`。

### `artifacts`

- 记录 draft 和 Vault note 的路径、SHA-256、状态及创建时间。
- 不保存笔记正文。

### `source_refs`

- 保存课程 ID、时间点/段落定位、来源 hash 和证据等级。
- 支持一条知识卡引用多个位置。

v0.1 的确定性检查验证来源定位的格式、范围及其 source hash 是否与当前课程一致，不独立证明定位内容正确。事实一致性仍由人工按原课程时间点复核。

### `workflow_events`

- append-only 状态变化审计：`from_state`、`to_state`、actor、reason、UTC 时间。

### `approvals`

- 记录本地人工批准，并绑定 `lesson_id + artifact_sha256 + source_hash`。
- draft 或 source hash 变化时，旧批准必须撤销，不能沿用。

### `source_reads`

- 逐页记录 `lesson_id`、source hash、语言、`track_sha256`、cursor/next cursor、字符数与 packet hash。
- 它是读取审计。草稿声明 `transcript_coverage=complete` 时，服务只接受相同 source hash、语言及对应 `track_sha256` 存在从 `0:0` 连续连接到末页的已记录 cursor 链；这证明接口覆盖，不证明 Host 正确理解了每页内容。

新生成课程卡的 frontmatter 包含 `source_language`、`transcript_coverage: complete|incomplete` 和 `visual_evidence: missing|reviewed|not_applicable`。`visual_evidence` 只能作为人工声明，MCP 不读取关键帧。未来版本会将线性 `status` 拆成 `capture / semantic / visual / publish` 四条正交状态，并增加 jobs、captures、segments、claims 与 publish receipts 表；旧表通过 migration 保留。

## 分页字幕契约

`get_review_packet` 使用 `(lesson_id, cursor, language, max_chars)` 读取单一字幕语言的一页，返回：

- 可选语言；
- 当前页语义段及时间范围；
- 不透明 `next_cursor`；
- 当前页已返回/总分段、字符数和时间范围；
- `complete` 标志。

响应还包含当前页 `packet_sha256`、缓存分段文件的 `segments_sha256` 和所选轨道 `track_sha256`。adapter 不信任分段 JSON 自报的 hash：每次读取都以独立大小上限和 no-follow/regular-file 检查流式读取相邻原始 VTT，在本地内存中重算原字幕 hash、重新解析分段并与 JSON 对照。原 VTT 正文不进入 state、日志、异常或 MCP 响应；工具只返回受 `max_chars` 约束的 segments。调用方必须把 cursor 当成只在同一课程、同一语言、同一 source hash 和同一 `track_sha256` 下有效的不透明值，不得跨课程或轨道复用。MCP Host 只有按顺序读到 `next_cursor=null`，并看到 `coverage.complete=true`，才能宣称该字幕轨读取完成。字幕覆盖不等于画面覆盖。

## 安全约束

- collector URL 必须是 `http://127.0.0.1` 或 `http://localhost`；health probe 会把 `localhost` 确定性归一到 `127.0.0.1`，禁用代理和重定向，将响应限制为 64 KiB，并且只返回白名单内的简短 status/version 元数据。
- 课程来源必须为配置的精确 HTTPS hostname；查询参数和 fragment 不落库。
- 课程 ID、Markdown 相对路径、扩展名和最大尺寸均校验。
- Vault 禁止绝对路径、`..`、`.git`、`.obsidian`、`.trash` 和符号链接逃逸。
- 原始 `WEBVTT`、多行字幕时间轴、`vtt_text`、媒体 base64、Cookie/Authorization 头不能进入知识卡。
- MCP 只暴露 Vault preview，不暴露 commit 工具。
- v0.1 禁止自动覆盖已有且内容不同的 Vault 文件；用户必须在 Obsidian 中人工合并。
- state、artifact 和发布变更通过 state 目录内的跨进程文件锁串行化，SQLite 状态转换同时使用事务/CAS 条件。
- 新文件先在同目录写临时文件并 `fsync`，再以不覆盖目标的原子 hard-link 发布并重读验证。
- v0.1 不暴露 delete/purge、任意 URL fetch、任意文件读取或通用浏览器控制。

## 已知边界

- 本地 CLI 的批准记录证明有人在本机执行了命令，但不是复核者身份认证；多人团队需要额外审计规范。
- legacy adapter 只兼容现有 collector JSON 合约，不包含 collector/Chrome 扩展，也不控制其 start/pause。
- v0.1 不自动生成跨课程金字塔和规则卡，只提供受约束 prompt；应在第二版加入 claims/evidence 图。
- v0.1 不把关键帧或视频画面暴露给 MCP；依赖画面的课程结论必须人工复核并标记视觉证据状态。
- 云端 MCP Host 获取 `get_review_packet` 后，有限源片段可能离开本机；完全离线需要本地模型。
- 确定性内容扫描用于降低明显泄露风险，不是秘密扫描或事实正确性的完整证明。
