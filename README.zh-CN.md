# claude-envlock

**非官方项目。为 macOS 上的 Claude Code 提供隔离、锁定的启动环境。**

失败即阻断的代理门禁 · 出口 IP 白名单 · 配置变化检测 · 以 `claude.env` 为唯一可信配置。

[![CI](https://github.com/wangjiancn/claude-envlock/actions/workflows/ci.yml/badge.svg)](https://github.com/wangjiancn/claude-envlock/actions/workflows/ci.yml)

[English](README.md) · [简体中文](README.zh-CN.md)

如果你通过本机 HTTP 代理（Clash、Surge、公司代理等）访问 Claude，配置错误的终端或悄悄停止的代理可能让流量走错路径。`claude-envlock` 包装每个 Claude 入口：**启动前先检查代理，检查失败就拒绝启动**。

| 入口 | claude-envlock 的处理 |
| --- | --- |
| 终端中的 `claude` | 门禁检查 → 强制代理环境变量 → `exec` 原始 CLI |
| VS Code 官方 Claude Code 扩展 | 通过 `claudeCode.claudeProcessWrapper` 走同一门禁 |
| `claude-web` / **Claude Envlock.app** | 门禁检查 → 独立 Chrome 资料，强制代理并加固 DNS、WebRTC、QUIC |

此外，`~/.claude-env/claude.env` 是 Claude 环境的**唯一可信配置**：只要实际配置与它不一致，或代理出口 IP 不在白名单内，启动时就会弹出 **Block / Continue（阻止 / 继续）** 选择框。

**不修改**代理节点、分流规则、系统代理、系统语言、系统时区、字体或默认浏览器。无需 pip / npm，使用 macOS 自带 Python。

> 本项目与 Anthropic 无关，也未获其认可。请遵守 Anthropic 的[使用政策](https://www.anthropic.com/legal/aup)与[支持地区](https://www.anthropic.com/supported-countries)。这是网络卫生工具，不用于隐藏身份。

## 工作原理

```
claude ──► 门禁：经 127.0.0.1:<端口> CONNECT claude.ai:443 ──► 校验源站 TLS 证书 ──► exec 原始 claude
               │                                              （不发 HTTP 请求、Cookie 或 Token）
               └── 任一失败 ──► 打印原因、退出码 1、绝不运行原始 CLI
```

此外每个包装器在启动前都会：

- 设置大小写两套 `HTTP(S)_PROXY`，移除 `ALL_PROXY` 和外部 `NO_PROXY`；
- 设置 `BROWSER=claude-web`，让 OAuth 链接在独立 Chrome 中打开；
- 关闭 Claude Code 非必要流量、遥测和错误上报；
- 可选：仅为 Claude 进程固定 `TZ`（见下文）。

详见 [docs/architecture.md](docs/architecture.md)、[docs/security-model.md](docs/security-model.md)。

## 环境要求

- macOS（已在 Apple Silicon 测试），`/usr/bin/python3` 3.9+（随 Xcode 命令行工具提供）
- 监听 `127.0.0.1` 的本机 HTTP 代理（默认端口 `7890`）
- Claude Code CLI（Homebrew、npm 或原生安装）；可选 VS Code 官方扩展、Google Chrome
- zsh（macOS 默认 shell）

## 安装

```sh
git clone https://github.com/wangjiancn/claude-envlock.git
cd claude-envlock
./install.sh --dry-run          # 只报告将修改的内容，不写入
./install.sh --port 7890        # 安装
```

安装后**打开新终端**，并在 VS Code 执行 **Developer: Reload Window**。已在运行的进程不会读取新配置。

| 参数 | 含义 |
| --- | --- |
| `--port N` | 本机代理端口；默认沿用上次，否则 `7890` |
| `--timezone 区域/城市` | 仅为 Claude CLI / IDE 进程固定 `TZ`；默认不启用 |
| `--no-timezone` | 取消固定 `TZ` |
| `--exit-ips "IP 网段 …"` | 出口 IP 白名单（`""` 关闭） |
| `--on-mismatch prompt\|block` | 发现配置变化或出口 IP 不符时：弹窗询问 / 直接阻止 |
| `--claude 路径` | 要包装的原始 CLI（可重复）；默认自动检测 `/opt/homebrew/bin`、`/usr/local/bin`、`~/.local/bin` |
| `--chrome 路径` | Chrome 可执行文件 |
| `--app-dir 路径` | `Claude Envlock.app` 位置，默认 `/Applications` |
| `--merge-unmanaged-settings` | 保留 Claude 自己写入 `~/.claude/settings.json` 的设置（如 `tui`） |
| `--dry-run` | 仅预检 |

重复安装是安全的：幂等、保留 VS Code JSONC 注释、不重复添加 shell 配置。若受管文件部署后被手动修改，安装器会**停止并指出该文件**，不会强行覆盖。

## 使用

```sh
claude-check              # 代理、TLS、出口 IP、配置检查的完整报告（不弹窗）
claude-check --country    # 额外的第三方国家诊断（仅供参考）
claude                    # 经门禁的 Claude CLI
claude-npm --version      # 经门禁的 Homebrew/npm 版本
claude-native --version   # 经门禁的原生安装版本
claude-web                # 独立 Chrome 打开 https://claude.ai/
claude-web 'https://…'    # 独立 Chrome 打开任意 HTTPS 地址（如 OAuth 链接）
```

也可从 Finder、Spotlight 或 Dock 打开 **Claude Envlock.app**。修改端口前须完全退出独立 Chrome。

## `claude.env`：Claude 环境的唯一可信配置

```sh
# ~/.claude-env/claude.env
export CLAUDE_ENVLOCK_PORT="7890"
export CLAUDE_ENVLOCK_TIMEZONE=""                                  # 空 = 系统时区
export CLAUDE_ENVLOCK_ALLOWED_EXIT_IPS="203.0.113.10 198.51.100.0/24"
export CLAUDE_ENVLOCK_ON_MISMATCH="prompt"                         # 或 "block"

# ---- 传给 Claude 的额外变量（可自行添加）----
export ANTHROPIC_MODEL="claude-opus-5-5"

# ---- 以下由上方设置生成，请勿手改 ----
export HTTP_PROXY="http://127.0.0.1:7890"
...
```

- **修改配置：** 编辑该文件后运行 `./install.sh`，在一次事务里同步到 Claude 设置、VS Code、启动器和 shell 配置。命令行参数也只是修改这个文件，省略的参数保持文件中的原值。
- **脚本复用：** `source ~/.claude-env/claude.env` 即可获得与 Claude 相同的代理和变量。格式是严格的 shell 子集，可以安全地 source。
- **额外变量** 会传给 CLI、VS Code 扩展和 `~/.claude/settings.json`；删掉某行并应用后，该变量会在所有地方被移除。
- 生成的行每次应用都会重写；手改生成行会被安装器拒绝，并提示应该修改哪个设置。

### 每次启动的配置检查

| 对象 | 检查方式 |
| --- | --- |
| 启动器、运行代码、`config.json`、`claude.env`、应用 | 与安装时的 SHA-256 完全一致 |
| `~/.claude/settings.json` | 只检查受管 `env` 值（Claude 可以自由写入自己的设置，如 `tui`） |
| VS Code 设置 | 只检查 `claudeProcessWrapper` 和受管环境变量 |
| `.zshrc` / `.zprofile` | 受管块存在且未被修改 |

编辑了 `claude.env` 但还没应用，也算配置变化。

### 出口 IP 白名单

设置 `CLAUDE_ENVLOCK_ALLOWED_EXIT_IPS` 后，每次启动经代理向 `https://claude.ai/cdn-cgi/trace` 发一次不带 Cookie 的请求（约 1 秒），读取 `ip=` 字段。因为请求的是 `claude.ai` 本身，代理会按**与真实 Claude 流量相同的规则**转发，比第三方 IP 查询网站可靠。支持单个 IP 和 CIDR 网段，IPv4、IPv6 均可。`claude-check` 会显示当前出口 IP，方便你填写白名单。

### 不一致时怎么处理

- **代理不可用或 TLS 无效：** 总是阻止，不弹窗。
- **配置变化或出口 IP 不在白名单：** 弹出 macOS 对话框列出问题，按钮为 **Block**（默认）和 **Continue**。Continue 只放行这一次，不会接受改动；要永久生效，请用 `./install.sh` 应用。没有图形界面时（如 SSH）改在终端询问；两者都不可用就阻止；120 秒内没人回应也阻止。
- 设置 `CLAUDE_ENVLOCK_ON_MISMATCH="block"` 则一律阻止，不弹窗。
- 每次选择都记录在 `~/.claude-env/decisions.log`（`0600`）。
- `claude-check` 从不弹窗：列出所有检查结果，有任何问题就退出码 1，适合脚本使用。

### 可选：为 Claude 进程固定时区

```sh
./install.sh --timezone Asia/Jakarta
```

只影响 Claude CLI、其子进程以及 VS Code 扩展进程，写入 `~/.claude/settings.json` 和 VS Code 的 `claudeCode.environmentVariables`。终端本身、macOS 和独立 Chrome 仍使用真实系统时区。该值在重复安装时保留，用 `--no-timezone` 取消。

## 卸载 / 回滚

```sh
~/.claude-env/bin/claude-rollback --check   # 预检
~/.claude-env/bin/claude-rollback           # 恢复原始文件
```

先退出独立 Chrome。回滚是“全有或全无”：只要有受管文件在部署后被改动，就不恢复任何文件并列出冲突。Chrome 资料与备份保留在 `~/.claude-env`。

> `~/.claude-env/backups/manifest.json` 含原始配置，`chrome-profile/` 含登录状态，**都不要分享**。

## 不保护的范围

使用前请阅读 [docs/security-model.md](docs/security-model.md)。简而言之：这不是系统级网络沙箱；直接执行原始二进制、其他 IDE、Claude 桌面版和日常浏览器都不在保护范围内；代理内部是否回退 DIRECT、出口节点由你的代理配置决定；配置检查能发现误操作和意外修改，防不了恶意软件（以你的身份运行的程序可以同时修改文件和备份记录）；出口 IP 只在启动时检查，代理仍可能在会话中途切换节点；不做指纹伪装，不承诺账号安全。

## 开发

```sh
make test     # 或 /usr/bin/python3 -m unittest -v
make smoke    # 真实 Claude 调用（消耗额度，上限 1 美元），见 docs/testing.md
```

完整人工验收方案（中文）：[docs/zh-CN/acceptance.md](docs/zh-CN/acceptance.md)。

## 许可证

[MIT](LICENSE)
