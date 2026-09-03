# Course Vault MCP

把用户**有权访问**的在线课程，经来源定位、人工复核和确定性发布校验，整理成 Obsidian 课程卡的本地 MCP 控制层。

> 当前版本：`0.1.0`。v0.1 是**控制、审核与发布层**，不是独立的视频下载器，也不是“输入账号后一键抓完整课程”的工具。

## v0.1 到底包含什么

| 能力 | v0.1 |
|---|---|
| 导入既有 collector 的课程元数据、状态和 hash | 包含 |
| 分页、限长读取临时字幕语义段 | 包含 |
| 生成并保存来源可定位的课程卡草稿 | 由 MCP Host 生成，MCP 保存 |
| 确定性校验与状态审计 | 包含 |
| Obsidian 预览、拒绝覆盖、原子写入和 SHA-256 回执 | 包含；真正写入只允许本地 CLI |
| 自动输入账号、密码或 MFA | **不包含** |
| Chrome 扩展和 localhost collector 本体 | **不包含**；需另行安装兼容组件 |
| 控制扩展的开始、暂停、换课或重试 | **不包含** |
| 下载视频、绕过 DRM/付费墙或导出 Cookie | **不包含，也不应加入** |
| 向 MCP 暴露视频画面或关键帧 | **暂不包含** |
| 自动生成跨课程金字塔、规则库或盈利策略 | **暂不包含** |

因此，从零开始使用需要三个本地组件：

```text
用户已登录的 Chrome + 兼容课程采集扩展
                    ↓
          localhost collector
                    ↓
 Course Vault MCP → staging → 本地 CLI 批准 → Obsidian Vault
```

本仓库目前只提供最后一层。若没有兼容 collector 和扩展，请先完成它们的安装；仅安装本仓库无法采集课程。

## 认证与内容边界

账号、密码、MFA、Cookie 和浏览器 profile 都不应进入 MCP：

1. 用户亲自在自己的 Chrome 中登录课程网站；
2. 受限扩展复用当前标签页的已登录会话，只读取播放器正常提供的字幕；
3. localhost collector 校验域名、课程 ID、格式、大小和 hash；
4. MCP 只编排导入、草稿和预览，不接触凭据，也不替用户操作登录页面。

登录失效时，用户应回到 Chrome 自行重新认证。不要把账号、密码、MFA、Cookie 文件、认证头或浏览器 profile 交给 MCP Host。

“本地 MCP”也不自动等于“内容完全不离开电脑”。如果 MCP Host 使用云端模型，`get_review_packet` 返回的有限字幕片段可能由该服务处理。完全离线需要兼容的本地 MCP Host/模型，或者把 `allow_bounded_source_segments` 设为 `false` 并采用人工离线复核流程。

## 质量门工作流

```text
用户在 Chrome 人工登录
  → 外部扩展与 collector 采集正常提供的字幕
  → 临时字幕分段 + hash-only 台账
  → MCP Host 分页读取，并生成 ai-draft
  → 用户或合格复核者按课程时间点复核
  → 本地 CLI 记录批准
  → 确定性隐私/路径/hash/来源定位校验
  → MCP 或 CLI 生成 Obsidian dry-run
  → 用户在本地 CLI 明确 commit
  → 原子写入 + SHA-256 回执
```

状态严格递进：

```text
discovered → captured → drafted → reviewed → validated → synced
       ↘ auth_required / failed / needs_attention
```

`captured` 不等于已经理解，`ai-draft` 不等于课程事实，`synced` 不等于知识已经完整，更不等于交易策略已经有效。

## 安装与首次运行

需要 macOS 或 Linux、Python 3.11+、一个已经存在的 Obsidian Vault 目录，以及兼容的外部 collector/Chrome 扩展。v0.1 依赖 POSIX 文件锁和 no-follow 文件 API，不支持 Windows。

在已经 clone 的仓库目录中执行：

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
cp examples/course-vault.example.toml course-vault.toml
```

编辑 `course-vault.toml`，填写 collector、临时缓存和 Vault 的路径以及精确课程域名。相对路径以配置文件所在目录为基准；建议对私人 workspace、缓存和 Vault 使用绝对路径。`state_dir` 必须位于配置/代码仓库之外，并与 Vault 拓扑隔离；示例将其放在仓库同级目录。v0.1 的 `require_human_review` 必须保持 `true`，不能通过配置绕过人工批准门。`course-vault.toml` 可能包含私人路径，已被 `.gitignore` 排除，不应提交 Git。

Vault 根目录必须提前创建，并至少用 Obsidian 打开确认一次；本地发布器会创建允许的课程子目录，但不会替你创建一个新的 Vault。本工具直接写 Markdown，不要求安装 Obsidian Local REST API 插件，Obsidian 应用也不必一直运行。

先确保 collector 已产生兼容 manifest，再执行：

```bash
.venv/bin/course-vault --config /absolute/path/course-vault.toml doctor
.venv/bin/course-vault --config /absolute/path/course-vault.toml refresh
.venv/bin/course-vault --config /absolute/path/course-vault.toml next
```

注意：`doctor` 会初始化 state 目录和 SQLite 台账，因此不是纯只读命令。它报告 collector 是否可达、manifest/cache 一致性和当前策略，但 `reachable: false`、缺少分段或配置错误都需要处理后才能采集或复核。

完整的第一次安装、连接、验收、停用和恢复步骤见 [FIRST_RUN.md](docs/FIRST_RUN.md)。旧 collector/课程卡接入见 [BROOKS_INTEGRATION.md](docs/BROOKS_INTEGRATION.md)。

## 连接 MCP Host

本地默认使用 `stdio`。下面是通用配置形状；实际配置文件位置、添加方式和重载方法取决于 Codex、Claude Desktop、Cursor 等具体 Host：

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

连接后必须确认 Host 能列出 `doctor`、`refresh_collector` 和 `next_action`，再让它处理真实课程。推荐第一条指令：

```text
调用 course-vault 的 doctor 和 refresh_collector，只报告状态和下一步；
不要声称已经完成人工复核，也不要尝试写入 Obsidian。
```

v0.1 在代码层只允许 `stdio`，不启用 HTTP transport。若未来增加远程
transport，必须另行设计认证、TLS、Host/Origin 白名单和最小权限工具集。

## CLI 与 MCP 工具的区别

CLI 是本机信任边界，负责诊断、记录人工批准和真正写入：

- `doctor`、`refresh`、`next`、`list`；
- `audit-legacy` 只读检查旧卡兼容性；`import-legacy LESSON` 预览旧卡导入，显式加 `--commit` 才复制到 staging；
- `approve LESSON --reviewer-note TEXT --confirm-source-check` 记录人工来源复核；
- `acknowledge-source-change LESSON --note TEXT --confirm-recapture` 在来源 hash 变化并人工检查/重采后回到 `captured`；
- `request-revision LESSON --reason TEXT` 将已审核或已校验成果退回 `drafted`，同时撤销批准；
- `validate`、`preview-sync`；
- 经用户明确确认后执行 `sync LESSON --commit --confirm-publish`。

MCP Host 只负责受约束的预发布编排，不拥有批准或发布权限；字幕片段仍是敏感源材料：

- `doctor`：报告 collector、SQLite、Vault 和策略状态；
- `refresh_collector`：只导入课程元数据、hash 和队列状态；
- `list_lessons`、`next_action`：查看进度与下一道质量门；
- `get_review_packet`：按课程、语言和 cursor 分页读取限长语义段，并返回覆盖率；
- `save_lesson_draft`：在 Vault 外保存原创课程卡草稿，并写入字幕语言、coverage 声明和视觉证据状态；
- `audit_legacy_cards`、`preview_legacy_card_import`、`import_legacy_card`：检查并把兼容旧卡复制成未批准的 content-addressed staging draft；
- `validate_lesson_draft`：执行隐私、大小、路径、draft/source hash 和来源时间范围语法检查；
- `preview_lesson_in_obsidian`：只返回发布预览，不写 Vault；
- `recent_workflow_events`：读取 append-only 状态审计。

人工批准和真正发布不暴露为 MCP 工具，防止模型把自己的草稿自行升级成课程事实，或在没有用户确认时写入 Vault。

v0.1 对已有且内容不同的 Vault 文件采用 fail-closed：返回 `VAULT_CONFLICT`，不提供 MCP 或 CLI 自动覆盖。用户应保留两份内容并在 Obsidian 中人工合并；内容完全相同则安全地返回未写入但已验证的回执。

## 字幕分页与覆盖率

`get_review_packet` 使用以下契约：

```text
get_review_packet(
  lesson_id,
  cursor = null,
  language = null,
  max_chars = configured_limit
)
```

响应给出 `available_languages`、`language`、当前页分段、`cursor`、`next_cursor`、`characters`、`packet_sha256`、`track_sha256`、`segments_sha256` 和 `coverage`。其中 `coverage` 包含 `returned_segments`、`total_segments`、`through_segment`、本页时间范围和 `complete`。每次读取时，adapter 会在本地以内存方式重算原始 VTT 的 SHA-256，并用相同算法重新分段后核对 `*.segments.json`；原始 VTT 不写入 state、日志或工具响应，MCP 工具仍只返回限长 segments。MCP Host 必须固定一种语言，逐页读取到 `next_cursor = null`，并核对 `coverage.complete=true`。多语言字幕是平行证据，不应在同一个字符额度内混合后误算为更高覆盖率。

每次读取会写入 `source_reads` 审计。保存草稿时可传入 `source_language`、`transcript_coverage_complete` 和 `visual_evidence`；只有相同 source hash、语言及对应 `track_sha256` 存在从 `0:0` 连续连接到末页的已记录 cursor 链时，系统才接受 `transcript_coverage_complete=true`。这证明接口层没有跳页，但不证明模型正确理解了每一页，语义质量仍需人工复核。

`visual_evidence` 只接受 `missing`、`reviewed` 或 `not_applicable`。它目前是人工声明，不是 v0.1 自动视觉核验。覆盖率只描述指定字幕轨，不证明字幕准确，也不证明视频画面已被理解；依赖图表、动作演示、幻灯片或屏幕文字的结论必须保持 `visual_evidence: missing`，直到用户回到原课程时间点完成画面复核。

## 旧项目迁移

`legacy_manifest` adapter 可以读取以下既有结构：

```text
collector/config/targets.prototype.json
collector/data/manifest.json
collector/data/review-queue.json
/private/tmp/<collector-cache>/<lesson>/*.segments.json
/private/tmp/<collector-cache>/<lesson>/<language>.vtt
```

旧课程卡和 hash 台账可以迁移，但旧系统的状态名不自动等价于 MCP 的质量门。legacy `reviewed` 最高只导入为 `captured`；用户先用 `import-legacy LESSON` 预览，再以 `--commit` 导入 staging，之后仍需通过本地 CLI 完成一次来源复核批准。升级时，系统只会对仍处于 `discovered`/`captured`、且没有 draft artifact、source refs 或有效批准的课程，把可验证的旧集合 hash 重键为新的语言映射 hash，并记录迁移事件；旧 `source_reads` 不会满足新 hash 的 coverage。其他 hash 变化仍进入 `needs_attention`。

如果临时分段仍在，可做定向来源复核；如果分段已被清理，已有原创课程卡仍可保留和登记，但需要重新核对原课程内容时，必须只对相关课程定向重采。不要因为 manifest 中仍有 hash 或旧 `reviewed` 状态，就宣称源内容仍可复核或整库无需重采。

## 已知边界

- v0.1 不控制外部扩展的 start/pause，也不负责跨页面批量导航；
- v0.1 暂不暴露视频画面或关键帧；
- v0.1 不自动生成跨课程金字塔和规则卡；
- 字幕覆盖、人工来源复核、Obsidian 发布和策略有效性是四件不同的事；
- 删除缓存没有暴露为 MCP 工具，避免模型误删不可恢复的会员源材料。

## 测试

核心测试使用合成数据，不需要真实课程内容：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/audit_public_export.py
```

安装依赖后可再用官方 MCP Inspector 检查工具契约。通过单元测试只说明合成路径工作，不等于真实 collector、登录会话、字幕完整性或 Vault 权限已经验证。

## GitHub 数据边界

仓库可以保存代码、空配置、Schema、模板和合成测试；禁止提交：

- 账号、密码、MFA、Cookie、token、storage state 或浏览器 profile；
- 会员字幕、视频、关键帧、签名媒体 URL 或课程附件；
- SQLite 私有台账、真实 targets/queue/manifest、运行日志；
- 个人 Obsidian Vault 或大段付费课程正文。

发布前流程见 [GITHUB_RELEASE.md](docs/GITHUB_RELEASE.md)。架构、完整工作流、隐私政策和相关项目分别见 [ARCHITECTURE.md](docs/ARCHITECTURE.md)、[WORKFLOW.md](docs/WORKFLOW.md)、[PRIVACY.md](PRIVACY.md)和 [RELATED_PROJECTS.md](docs/RELATED_PROJECTS.md)。

## 许可证

程序代码采用 MIT。课程内容、用户生成的知识库及第三方网站材料不因本代码许可证获得任何授权。
