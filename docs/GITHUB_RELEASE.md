# GitHub 发布、升级与恢复

代码仓库与私人课程 workspace 必须物理分离，即使目标 GitHub 仓库是 private。private repository 不是会员内容备份位置，也不是降低版权、凭据或隐私要求的理由。

## 1. 发布前本机检查

在仓库根目录运行：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'
git status --short --ignored
```

先完成下一节的明确暂存，再运行审计。`audit_public_export.py` 检查将提交的 Git index blob 和全部本地 Git 历史，不读取未暂存工作树来替代 index；它仍不是完整的 secret scanner，也不会证明第三方内容有再发布授权。

人工再次确认不存在：

- `course-vault.toml`、`.env`、SQLite、缓存、备份或日志；
- VTT/SRT、图片、视频、签名媒体 URL；
- 账号、Cookie、token、MFA、storage state 或浏览器 profile；
- `/Users/<name>/...` 等个人绝对路径；
- 真实课程 targets、manifest、queue、知识 Vault；
- 会员课程原文、连续字幕、真实关键帧或附件。

## 2. 明确暂存，而不是整库盲加

首次提交优先逐项暂存预期的公开文件，不建议在私人 workspace 邻近目录执行未经检查的 `git add .`。暂存后重新运行审计：

```bash
git diff --cached --name-status
git diff --cached --check
python3 scripts/audit_public_export.py
git diff --cached
```

只有人工检查 staged diff 后才提交。审计后不要再添加文件而不重跑审计。

## 3. 先推送 private repository

1. 在 GitHub 创建一个**空的 private repository**，不要自动添加 README、License 或 `.gitignore`。
2. 在本地添加该仓库的准确 remote；不要复制粘贴来源不明的 remote URL。
3. 再次确认 `git status`、审计结果和首个 commit。
4. 推送 `main`，随后在 GitHub 网页核对文件树；搜索个人路径、课程站名、常见 secret 前缀和字幕扩展名。
5. private 仓库核对无误后，再决定是否公开。公开是单独的高风险决策，不应与第一次 push 合并。

如果使用 GitHub CLI，可在确认账号和目标名称后采用以下形状；尖括号必须替换为实际值：

```bash
gh auth status
gh repo create <owner>/<repository> --private --source=. --remote=origin
git push -u origin main
```

不要在文档、shell history 或 remote URL 中放入访问 token。

## 4. 仓库设置

建议启用：

1. secret scanning 与 push protection；
2. private vulnerability reporting；
3. `main` 分支保护和必须通过的 CI；
4. 最小 Actions 权限；
5. Dependabot 或同类依赖更新检查。

CI 使用固定 commit 的 GitHub Actions，并按 `requirements.lock.txt` 安装已审核的依赖快照。升级 MCP 或任一传递依赖时，应在支持的 Python 版本矩阵上重建并复核 lock；当前 lock 固定版本但未包含跨平台 wheel hash，因此仍需依赖 GitHub/PyPI 的供应链保护。

禁止 Actions 上传运行目录、测试截图、collector artifacts、Obsidian Vault 或 state 目录。CI 只能使用动态生成的合成课程 fixture。

## 5. 首版提交与版本

代码、文档和运行时统一使用 `0.1.0`。建议把初始工作拆成可检查的提交：

```text
feat: scaffold local course-vault MCP
test: add workflow and security gates
docs: document authentication and content boundaries
```

完成 private 仓库核对后再创建 tag/release：

```bash
git tag -a v0.1.0 -m "Course Vault MCP 0.1.0"
git push origin v0.1.0
```

release 只附代码和公开文档，不附 `.venv`、构建缓存、真实配置或运行 artifacts。发布公开版本前，逐项确认课程网站条款、第三方许可证和引用。

不要把私有 workspace 作为 Git submodule，也不要用 Git LFS 保存会员素材。

## 6. 升级

升级前：

1. 断开 MCP Host，并停止正在运行的 collector；
2. 一致性备份私人 `course-vault.toml`、state SQLite、staging 草稿和发布回执；
3. 保存当前版本号和配置 schema；
4. 阅读 release notes 和 migration 说明；
5. 在副本或合成 fixture 上先运行测试。

从源码安装的常规升级流程是拉取受信任 tag、重新执行 editable install、运行测试与 public-export audit，再启动 `doctor`。不要在真实 Vault 上用未经检查的开发分支做首次迁移。

升级后第一次 `refresh` 可能迁移早期开发版的 source fingerprint。只有仍处于 `discovered`/`captured` 且没有 artifact、source ref 或有效批准的课程会原状态安全换算并记录 migration event；存在下游证据时必须进入 `needs_attention`。先查看事件和状态数量，再继续批处理。

## 7. 恢复与回滚

- 代码回滚到先前 tag 不会自动回滚 SQLite schema、staging 或 Vault 文件。
- v0.1 不覆盖既有且不同内容的 Vault 笔记，因此不会生成覆盖前备份；如需历史恢复，必须使用 Obsidian、版本控制或文件系统自己的私人备份方案。
- SQLite 恢复应使用停机时创建的一致备份，不要复制正在 WAL 写入的单个数据库文件后假定其完整。
- 如果怀疑凭据或会员内容进入 Git 历史，先立即把仓库设为 private、撤销相关凭据并停止推送；仅删除工作树文件不能清除历史，应按 GitHub 的敏感数据清理流程重写历史并通知已有 clone 的使用者。

## 8. 停用与卸载

1. 从 MCP Host 配置中删除或禁用 `course-vault`，并重启/重载 Host。
2. 断开 MCP Host、停止 collector 进程，并禁用课程采集扩展。
3. 删除 `.venv` 只会卸载本地 Python 环境，不会删除 state、草稿或 Vault 笔记。
4. 是否删除临时字幕缓存由用户按 [WORKFLOW.md](WORKFLOW.md) 的清理证据门决定。
5. 删除私人 state 或备份前，确认不再需要审计、恢复或重新发布。
