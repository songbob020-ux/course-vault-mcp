# 第一次安装与端到端验收

本指南面向第一次从 GitHub 取得代码的使用者。v0.1 仅支持 macOS/Linux；它依赖 POSIX 文件锁和 no-follow 文件 API，不支持 Windows。

最重要的前提：本仓库不包含 Chrome 采集扩展或 localhost collector。没有兼容外部组件时，只能运行合成测试和查看 MCP 契约，不能登录或采集课程。

## 1. 准备清单

- macOS 或 Linux；
- Python 3.11 或更高版本；
- 已 clone 的 Course Vault MCP 仓库；
- 已存在并可正常打开的 Obsidian Vault；
- 兼容版本的 localhost collector；
- 兼容版本的 Chrome 扩展；
- 用户有权访问的课程账号；
- 支持 stdio MCP 的 Host。

开始前先决定内容是否可以发送给云端模型。如果不可以，必须使用兼容本地模型，或在配置中关闭 `allow_bounded_source_segments`。关闭后 MCP Host 不能读取字幕，课程卡只能走人工离线流程。

## 2. 安装 Course Vault MCP

进入仓库根目录：

```bash
python3 --version
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/course-vault --help
.venv/bin/course-vault-mcp --help
```

如果最后一个入口直接启动 stdio 服务而不显示 help，使用 `Ctrl+C` 停止即可；正常情况下 MCP Host 会负责启动它。

先用合成数据确认安装没有破坏：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/audit_public_export.py
```

测试通过只说明软件安装成功，不说明真实课程采集链已经工作。

## 3. 准备 Obsidian Vault

1. 在 Obsidian 中创建或选择一个 Vault。
2. 打开一次并确认能够手工新建、保存 Markdown 笔记。
3. 记录 Vault 根目录的绝对路径。
4. 决定专用课程子目录，例如 `Courses/My Authorized Course`。

本工具不要求安装 Obsidian Local REST API 插件。本地发布器直接写 Markdown；真正 commit 只从本地 CLI 暴露。

## 4. 创建私人配置

```bash
cp examples/course-vault.example.toml course-vault.toml
```

填写：

- 唯一 `project_id` 和标题；
- 位于配置/代码仓库之外、且不在 Vault 内的私人 state 目录；
- collector 私人项目和 cache 的绝对路径；
- collector localhost URL；
- 精确课程 HTTPS hostname allowlist；
- Vault 根目录和课程子目录；
- 是否允许 MCP Host 读取有限字幕段。
- `require_human_review = true`；v0.1 会拒绝关闭人工批准门的配置。

相对路径以 TOML 文件所在目录为基准。运行配置、SQLite、字幕缓存和 Vault 均不得提交 Git。可用下面的命令确认 Git 忽略状态：

```bash
git status --short --ignored
```

不要把真实配置贴进 issue、聊天或截图。

## 5. 安装并启动外部采集链

这一步必须遵循所使用 collector/扩展自己的受信任安装说明；Course Vault MCP 不能代替它。

最低验收标准：

1. collector 只绑定 `127.0.0.1` 或 `localhost`；
2. 扩展版本与 collector 合约兼容；
3. 扩展只申请完成课程字幕采集所需的最小权限；
4. collector health endpoint 返回正常；
5. 扩展显示已经连接到正确的 localhost collector；
6. targets、manifest、queue 和 cache 路径与 TOML 一致；
7. 扩展不要求导出 Cookie、storage state 或浏览器 profile。

如果本项目发布时仍未提供外部组件的下载地址和固定兼容版本，则端到端安装仍然不完整；不要从搜索结果随意安装同名扩展。

## 6. 初始化台账

collector 至少需要先产生兼容的 targets、manifest 和 queue JSON。然后执行：

```bash
.venv/bin/course-vault --config /absolute/path/course-vault.toml doctor
.venv/bin/course-vault --config /absolute/path/course-vault.toml refresh
.venv/bin/course-vault --config /absolute/path/course-vault.toml next
```

`doctor` 会创建 state 目录和 SQLite，因此不是只读命令。检查输出时至少确认：

- 项目 ID、Vault `exists` 和课程子目录正确（绝对路径只在本地 TOML 中核对）；
- collector URL 是 localhost；
- `reachable` 与你要执行的动作相符；
- cache drift 为零，或每一个 drift 都有解释；
- 不存在意外课程域名；
- 状态数量符合预期。

collector 暂时离线时，已有 manifest 可能仍能导入；这只允许审计旧元数据，不允许宣称能够继续采集。

## 7. 连接 MCP Host

将以下通用配置形状添加到你的 MCP Host；配置文件位置和重载方法以 Host 的官方文档为准：

```json
{
  "mcpServers": {
    "course-vault": {
      "command": "/absolute/path/course-vault-mcp/.venv/bin/course-vault-mcp",
      "env": {
        "COURSE_VAULT_CONFIG": "/absolute/path/course-vault.toml"
      }
    }
  }
}
```

保存后彻底重载 MCP Host。验收时应能看到以下受约束工具；其中字幕读取和 staging 写入并非纯只读：

- `doctor`；
- `refresh_collector`；
- `list_lessons`；
- `next_action`；
- `get_review_packet`；
- `save_lesson_draft`；
- `audit_legacy_cards`、`preview_legacy_card_import`、`import_legacy_card`；
- `validate_lesson_draft`；
- `preview_lesson_in_obsidian`；
- `recent_workflow_events`。

不应出现人工 approve 或 Obsidian commit 工具。如果出现，停止使用并核对安装版本。

第一条建议指令：

```text
调用 course-vault 的 doctor 和 refresh_collector，只报告项目状态、缓存缺口和下一步。
不要声称完成人工复核，不要写入 Obsidian。
```

## 8. 人工登录并只采一课验收

1. 用户在 Chrome 打开允许的课程网站。
2. 用户亲自登录并处理 MFA。
3. 确认课程页面确实可播放/显示会员内容。
4. 在扩展中选择一节明确允许的测试课程。
5. 启动采集，等待 collector 将该课标为 `captured`。
6. 再调用 `refresh_collector`，确认 MCP 台账中只有预期变化。

不要第一次就启动全课程批次。单课验收要先证明课程 ID、来源域名、语言、分段、hash 和 cache 路径全部一致。

出现 `auth_required` 时回到 Chrome 重新认证；出现 `failed` 或 `needs_attention` 时检查一次具体错误，不要让模型无限重试。

## 9. 分页生成课程卡草稿

让 MCP Host：

1. 查看 `available_languages`；
2. 固定一种字幕语言；
3. 从 `cursor=null` 开始读取；
4. 使用返回的 `next_cursor` 继续，直到为 `null`；
5. 报告最终 `coverage.complete` 和时间覆盖；
6. 将字幕缺失、歧义及视觉缺口写入草稿；
7. 调用 `save_lesson_draft`，设置同一 `source_language`；只有确实顺序读到末页时才设 `transcript_coverage_complete=true`；
8. 将 `visual_evidence` 设为 `missing`、`reviewed` 或 `not_applicable`，并只写 staging。

建议指令：

```text
处理指定的一课。固定最合适的字幕语言，按 cursor 读取到 next_cursor=null；
先报告覆盖率，再生成带课程时间点、反例、待验证问题和 visual_evidence 状态的原创草稿。
只保存到 staging，不得批准或发布。
```

如果 `coverage.complete` 为 false，不要把状态描述成“本课已完整整理”。系统会要求 `transcript_coverage_complete=true` 对应同 source hash、语言及 `track_sha256` 从 `0:0` 连续到末页的已记录 cursor 链；仍然不要跳 cursor。接口覆盖不证明模型正确理解了各页。如果课程依赖图表、幻灯片或演示，保持 `visual_evidence: missing`。

## 10. 人工复核和本地批准

1. 打开 staging 草稿。
2. 回到原课程引用的时间点。
3. 核对字幕归纳和视频画面。
4. 发现问题时，让 MCP Host 保存一个修订后的新 draft；旧卡迁移则先修改私人旧卡，再重新 preview/import。
5. 不要直接修改 content-addressed staging artifact；新 draft 会使用新 hash，并撤销旧批准。
6. 用户在本地终端执行：

```bash
.venv/bin/course-vault --config /absolute/path/course-vault.toml \
  approve <lesson-id> \
  --reviewer-note "checked against cited course locations and required visuals" \
  --confirm-source-check
```

批准只能由用户在本地 CLI 执行，MCP Host 没有此权限。`--confirm-source-check` 是一次明确的本机操作，但不是复核者身份认证。

## 11. 校验、预览和发布

批准后执行：

```bash
.venv/bin/course-vault --config /absolute/path/course-vault.toml validate <lesson-id>
.venv/bin/course-vault --config /absolute/path/course-vault.toml preview-sync <lesson-id>
```

检查目标路径、`changed`、`before_sha256`、`after_sha256` 和字节数。新文件的 `before_sha256` 为 `null`。

用户确认后，才执行：

```bash
.venv/bin/course-vault --config /absolute/path/course-vault.toml \
  sync <lesson-id> --commit --confirm-publish
```

v0.1 不自动覆盖已有且内容不同的笔记；这种情况返回 `VAULT_CONFLICT`。用户应在 Obsidian 中人工比较和合并，不能通过删除原笔记来绕过冲突门。已有内容完全相同时不会重复写入。

发布后确认：

- receipt 显示 `verified: true`；
- SQLite 状态为 `synced`；
- Obsidian 中出现预期课程卡；
- 新生成卡的 frontmatter 包含正确的 `workflow_state: see-local-ledger`、`artifact_kind: lesson-card`、`source_language`、`transcript_coverage`、`visual_evidence` 和来源定位；legacy 原样导入卡可能没有这些字段，其状态以本地 ledger 为准；
- 没有字幕正文、私人路径或 credential；
- 已有且不同内容的笔记没有被自动覆盖。

## 12. 首次通过标准

只有同时满足以下条件，才算端到端验收成功：

```text
一课 captured
+ 单语言 pagination complete
+ draft 在 staging
+ 用户核对字幕和必要画面
+ 本地 CLI approval
+ deterministic validation
+ preview hash 经用户确认
+ 本地 CLI commit
+ Vault 写后 hash verified
```

这仍不证明课程结论可以盈利或自动执行。

## 13. 常见故障

### Vault root does not exist

先在 Obsidian 创建/打开 Vault，再修正 TOML。`doctor` 不能替你创建 Vault root。

### collector unreachable

确认进程正在运行、端口与 TOML 一致且只绑定 localhost。旧 manifest 可读不代表采集服务在线。

### manifest available but segments missing

hash 台账仍可审计，但不能做来源复核。只对需要复核的课程定向重采。

### legacy reviewed 变成 captured

这是预期的安全降级：旧状态不含 MCP draft、coverage 和本地批准证据。先预览旧卡导入，再显式复制到 staging：

```bash
.venv/bin/course-vault --config /absolute/path/course-vault.toml \
  import-legacy <lesson-id>
.venv/bin/course-vault --config /absolute/path/course-vault.toml \
  import-legacy <lesson-id> --commit
```

随后重新走人工来源复核和本地批准门。导入只是复制并绑定现有 source hash，不证明旧卡准确。

### VAULT_CONFLICT

目标文件已经存在且内容不同。v0.1 不支持自动覆盖；保留双方内容并在 Obsidian 中人工比较、合并或另存 revision。

### source hash changed

来源变更会使旧证据和批准失效，并停在 `needs_attention`。升级期间，只有仍为 `discovered`/`captured`、没有 artifact/source refs/有效批准且旧 hash 精确匹配已知旧算法时，系统才会自动重键并记录事件；旧读取链不会沿用。除此之外，定向重采、核对新来源后，由用户执行：

```bash
.venv/bin/course-vault --config /absolute/path/course-vault.toml \
  acknowledge-source-change <lesson-id> \
  --note "recaptured and checked after source update" \
  --confirm-recapture
```

课程回到 `captured`，必须重新生成/导入草稿和批准。

### 审核后需要修改

不要直接修改已批准 artifact。执行：

```bash
.venv/bin/course-vault --config /absolute/path/course-vault.toml \
  request-revision <lesson-id> --reason "explain what must change"
```

这会退回 `drafted` 并撤销旧批准；修订后重新走 approve、validate 和 preview。

### MCP Host 看不到工具

确认 executable 和 TOML 都是绝对路径，重新加载 Host，并在终端单独运行入口检查依赖错误。v0.1 不提供 HTTP transport。

## 14. 停用、恢复和升级

- 停用：从 Host 移除 MCP 配置并停止 collector；禁用扩展。
- 缓存：只有通过发布与 hash 门后才考虑人工删除；删除后复核需要定向重采。
- 恢复：一致性备份并保留 state SQLite、staging 和发布回执；v0.1 不覆盖既有笔记，也不自动生成覆盖前备份。
- 升级：先停止服务并备份私人状态，在合成数据上测试新版本，再迁移真实项目。
- 卸载：删除 `.venv` 不会删除 state 或 Vault；这些数据必须由用户另行、谨慎处理。

GitHub 发布和详细恢复边界见 [GITHUB_RELEASE.md](GITHUB_RELEASE.md)。
