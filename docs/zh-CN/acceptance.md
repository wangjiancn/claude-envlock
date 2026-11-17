# Claude 本机入口保护：完整验收方案

适用版本：claude-envlock 2.x。下文 `<repo>` 指本仓库目录，`<端口>` 指本机代理端口，`<时区>` 指通过 `--timezone` 设置的时区（未设置则跳过所有时区项）。

目标配置：本机 HTTP 代理 `127.0.0.1:<端口>`；Claude CLI 和 VS Code 官方扩展使用 `<时区>`；macOS 和专属 Chrome 继续使用真实系统时区。节点、订阅和代理内部的分流由用户维护。

## 1. 验收范围与判定规则

本方案验收终端包装器、两套原始 CLI 的受管入口、VS Code 官方扩展、专属 Chrome、Claude Envlock.app、故障阻断、配置保留、升级和回滚。

不把下列内容作为本工具的已实现能力：全系统流量隔离、防封号概率、修改节点国家、代理内部禁止 DIRECT、浏览器指纹伪装、Cline 或其他未配置客户端的保护。

### 判定等级

- **P0 核心项**：必须全部通过，才可给出“核心配置验收通过”。任一失败均需修复后复测。
- **P1 场景项**：真实浏览器网络行为、OAuth、网络切换与休眠。全部完成后，才可给出“完整验收通过”。没有测试条件时记为“待验”，不能记作通过。
- **诊断项**：仅记录，不作为保护能力通过的依据。例如第三方 IP 检测站的国家结果。

每个项目只允许记录：通过、失败、待验、不适用。“不适用”必须说明原因。出现失败时同时记录复现条件、实际行为、期望行为和修复后的复测证据。

本方案是操作规程，不代表这些项目已经全部执行。历史结果应单独保存在仓库外；本轮须重新记录日期、版本和证据。

## 2. 准备、证据与执行顺序

### 准备

1. 保存工作，退出旧 Claude CLI，在 VS Code 执行 **Developer: Reload Window**。
2. 保持日常代理和节点配置不变。确认需要验证的账号已具备正常使用 Claude 的条件。
3. 有 Python 3、Node.js、Chrome、VS Code 和两套 CLI。某套 CLI 未安装时，记录“不适用”，不要伪造该入口的结果。
4. 标记哪些 Chrome 窗口属于专属资料；只操作这一实例，不误关日常浏览器。
5. 先做无中断检查，再做真实模型与界面测试，最后安排断网、唤醒和恢复测试。

### 证据要求

- 每项保留编号、时间、应用/CLI 版本、执行入口、退出码、关键输出或截图。
- 脚本通过必须同时具备退出码 0 与符合预期的结果；模型文字声称“通过”不能代替工具输出。
- 真模型测试会消耗额度。现有运行器每次请求预算上限 1 美元、超时 120 秒；不反复重跑已经通过的请求。
- 原始日志留在本机 `~/.claude-env`，不要复制到可分享脚本目录；截图与摘要移除邮箱、账号 ID、Token、Cookie、授权链接和订阅地址。
- 为避免误认为历史结果是新结果，记录完整测试时间；`--report-only` 只验证上一次日志。

### 顺序

配置检查 → 自动回归 → CLI 真执行与界面 → VS Code → Chrome/应用 → 隔离故障 → 配置升级回滚 → 真实网络/OAuth场景 → 汇总签收。

## 3. P0 核心验收

### A01：配置一致性与重复部署预检

从当前工作目录运行：

```sh
cd <repo>
./install.sh --port <端口> --timezone <时区> --dry-run
```

**通过标准：** 退出码 0，报告端口 `<端口>`、CLI 时区 `<时区>`、待更新文件 0。检查全局 Claude 的 `env.TZ`、VS Code 的 `claudeCode.environmentVariables` 中的 TZ，以及本地运行配置 `cli_timezone` 三处一致。

若报告文件冲突，先记录差异，不能直接覆盖或编辑 manifest 来让检查变绿。只有确认是 `tui` 等非受管设置变化时，才使用安装器的 `--merge-unmanaged-settings` 合并并复测。

### A02：代理连通与源站 TLS

```sh
~/.claude-env/bin/claude-check
```

**通过标准：** 退出码 0，明确显示经 `http://127.0.0.1:<端口>` 对 `claude.ai:443` 的 CONNECT 与 TLS 校验成功。端口能连但 TLS 失败，应判定失败。

此结果验证配置端口和源站握手，不证明代理内部没有直连回退，也不证明出口国家。

### A03：自动回归

```sh
/usr/bin/python3 -m unittest -v
```

**通过标准：** 全部测试通过，最终输出 `OK`、退出码 0。后续若增加测试，以对应版本的清单为准；任何未解释的 skip、失败或异常都不能忽略。

保留测试输出，尤其关注 TLS 失败阻断、CLI/IDE 时区、浏览器不继承 TZ、升级合并和回滚保护。

### A04：新终端与两套 CLI 入口

在**新开的登录交互式终端**中运行：

```sh
whence -p claude
alias claude
claude-npm --version
claude-native --version
```

**通过标准：** 默认路径和别名均指向 `~/.claude-env/bin/claude`；两个受管版本入口均成功。原始 Homebrew/原生程序与符号链接仍存在，未被重命名为 `.real`。

版本号以当前安装为准，不要求永远等于历史记录。默认入口通过不代表直接执行原始绝对路径也经过包装器。

### A05：Claude CLI 真模型、真命令验收

```sh
/usr/bin/python3 tools/run_smoke.py
```

**通过标准：** 退出码 0、`pass: true`，验证器找到唯一预期 Bash 调用与对应成功工具返回，以下全部全为 true：

1. 四个 HTTP/HTTPS 代理变量均为 `http://127.0.0.1:<端口>`。
2. `NO_PROXY` / `no_proxy` 仅包含本机 loopback。
3. 无 SOCKS 环境变量覆盖。
4. 继承专属浏览器启动入口。
5. PATH 中 Claude 指向受管包装器。
6. 经代理 CONNECT/TLS 成功。
7. `TZ=<时区>`。
8. Node.js `Intl` 解析为 `<时区>`。

证据须包括工具执行结果，不能仅保存 Claude 的总结。脚本只检查指定环境字段，不应使用 `env` 全量输出或读取认证文件。

### A06：交互式额度面板时区

1. 完全退出原 CLI，会话重启后打开其额度/使用量面板；当前版本通常通过 `/usage` 进入。
2. 查看 session 与 week 的重置时间标签。
3. 保留遮盖账号信息后的截图；如要比较钟点，比较同一重置时刻，不能跨重置周期比较。

**通过标准：** 两处都显示 `<时区>`。时钟显示随时区换算，但账号额度和实际重置时刻不改变。

若 A05 通过而面板仍显示系统时区，A06 仍判失败；记录当前 CLI 版本，排查是否旧会话、未受管入口或面板格式化逻辑，不能用子进程时区结果代替界面结果。

### A07：VS Code 官方扩展实际面板

1. 确认扩展是 Anthropic 官方 Claude Code，重新加载 VS Code 窗口。
2. 确认 `claudeCode.claudeProcessWrapper` 指向本机 `~/.claude-env/bin/claude-ide-wrapper`。
3. 在**扩展面板中**发起请求，让 Claude 只运行：

```text
请只用 Bash 执行以下只读命令，并原样报告 JSON 结果：
/usr/bin/python3 <repo>/tools/smoke_probe.py
不要执行其他命令、读取其他文件或修改配置。
```

**通过标准：** 扩展真实完成 Bash 工具调用，全部均为 true，TZ/Intl 均为 `<时区>`。扩展错误日志不出现包装器路径/权限错误。

集成终端中的成功结果不代替扩展面板结果；扩展自带 CLI 的 `--version` 成功也不代替面板验收。授权提示仅批准这条测试命令。

### A08：专属 Chrome 与桌面入口

依次测试 `claude-web`、Finder 中的 `Claude Envlock.app`、固定到 Dock 后的应用图标。记录每个入口是否成功。

在专属 Chrome 打开 `chrome://version`，检查：

- 个人资料路径位于 `~/.claude-env/chrome-profile` 下。
- 启动命令行包含 `--proxy-server=http://127.0.0.1:<端口>`。
- 包含 `--force-webrtc-ip-handling-policy=disable_non_proxied_udp`、`--disable-quic` 和外部 DNS 解析限制参数。

**通过标准：** 三个入口均打开同一专属资料；没有混入日常 Chrome 登录资料；Claude 页面可加载。仅参数正确不代表 WebRTC/DNS 行为已通过 P1 测试。

### A09：系统与浏览器时区保持现状

在普通终端检查：

```sh
readlink /etc/localtime
```

在专属 Chrome 开发者工具 Console 执行：

```js
Intl.DateTimeFormat().resolvedOptions().timeZone
```

**通过标准：** macOS 仍为原系统时区，例如 `Asia/Shanghai`；浏览器同样使用真实系统时区。额外覆盖从 CLI 的 `BROWSER` 启动浏览器的路径，确认不会继承 CLI 的雅加达 TZ。不要为了让所有项目看起来一致而修改系统或浏览器时区。

### A10：启动前故障阻断

隔离测试覆盖：端口未监听、代理返回非 200、CONNECT 通过但 TLS 失败。通过临时测试目录和模拟代理执行，不改日常代理配置。

**通过标准：** CLI 不执行真实程序、返回非零；浏览器不创建新的浏览器进程；IDE 包装器不执行扩展二进制。错误信息说明失败，不输出凭据，不尝试其他端口或直连。

现有自动测试已覆盖核心门禁和 CLI 的部分路径；浏览器与 IDE 故障路径如尚无对应测试，须补足隔离用例或在隔离部署中实际验证，不能只凭代码推断记为通过。

### A11：无关配置、权限与日志

**通过标准：**

- 与部署前备份比较，模型选择、无关 env、VS Code 无关键值、JSONC 注释及 shell 原有内容保留。
- `~/.claude-env` 为 `0700`；备份、配置和原始模型日志为 `0600`；脚本可执行。
- 没有全局 `open` 拦截器，没有修改默认浏览器，没有删除 Cookie 或卸载应用。
- 可分享脚本目录不包含账号凭据、订阅或节点密码、原始备份、浏览器资料和会话日志。

检查权限使用 `stat` 或 `ls -ld`；不要为了取证打印备份全文。

### A12：重复安装、升级与回滚

先在临时 HOME 和独立 app 目录执行隔离测试，避免撤销当前工作环境。

**通过标准：**

- 同一参数重复部署无新增修改、无重复 shell 块。
- 无效时区在写配置前被拒绝；更改代理端口且 Chrome 未退出时被拒绝。
- CLI 更新后仍解析到真实程序；模拟原始程序缺失、递归包装或不受信任 IDE 路径时明确失败。
- 非受管 Claude 设置可显式合并，且回滚后保留；受管 env 被改动时仍停止。
- 完整回滚恢复原始内容和权限、保留浏览器资料及备份，不影响其他应用。
- 部署后文件被修改时，回滚拒绝执行，其他文件不发生部分回滚。

本机仅做回滚预检，先退出专属 Chrome：

```sh
~/.claude-env/bin/claude-rollback --check
```

除非本来就要撤销部署，不在日常环境执行不带 `--check` 的回滚命令。部分升级/缺失场景尚未被现有自动测试覆盖时，需补测并记录。

## 4. P1 真实使用场景验收

### B01：实际代理链路

分别从 CLI、VS Code 面板和专属 Chrome 发起一次正常请求。在 代理客户端（如 Clash 系客户端） 连接记录中，按对应时间和 `claude` / `anthropic` 目标定位连接。

**通过标准：** 三个入口都走用户已配置的规则和节点。记录目标域名、匹配规则、节点名称和时间；不要保存订阅地址或密码。

Cloudflare/ipinfo 的出口国家不同只作诊断，不据此调整节点，也不将其国家结果作为 Claude 实际出口证据。

### B02：WebRTC 实际行为

策略含义参照 [Chromium 官方 WebRtcIPHandling 定义](https://chromium.googlesource.com/chromium/src/+/main/components/policy/resources/templates/policy_definitions/WebRtc/WebRtcIPHandling.yaml)。候选地址对照方法参照 [WebRTC 官方 Trickle ICE 示例](https://webrtc.github.io/samples/src/content/peerconnection/trickle-ice/)；STUN 能产生 `srflx` 候选才说明对照服务有效。

在专属 Chrome 的开发者工具 Console 中执行以下一次性探测；测试会访问所列 STUN 服务：

```js
(async () => {
  const pc = new RTCPeerConnection({
    iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
  });
  const candidates = [];
  pc.onicecandidate = e => { if (e.candidate) candidates.push(e.candidate.candidate); };
  try {
    pc.createDataChannel('acceptance');
    await pc.setLocalDescription(await pc.createOffer());
    await new Promise(resolve => {
      const timer = setTimeout(resolve, 10000);
      pc.onicegatheringstatechange = () => {
        if (pc.iceGatheringState === 'complete') { clearTimeout(timer); resolve(); }
      };
      if (pc.iceGatheringState === 'complete') { clearTimeout(timer); resolve(); }
    });
    console.log(JSON.stringify({ candidates, state: pc.iceGatheringState }));
  } finally { pc.close(); }
})();
```

**通过标准：** 无经非代理路径暴露的真实公网候选地址。必须有有效对照：在独立的无账号临时 Chrome 资料中，同网络、同 STUN 服务可以取得公网候选地址，专属资料则未泄漏。不要在含账号资料的日常浏览器中做对照。

如果两个资料都没有候选地址，可能只是 STUN 不通或解析受限，记“待验”，不能据此证明防泄漏。若需证明无非代理 UDP 发包，还须结合按进程区分的网络观测；候选地址测试本身不作全量流量证明。候选地址原始输出仅本地保留。

### B03：DNS 行为

在专属 Chrome 中关闭账号页面及其他标签，只打开测试页，使用 Chrome NetLog 或能区分 Chrome 与代理进程的网络观测工具，打开一个本次未访问过的外部测试域名。先验证工具能在临时对照资料中捕获一次明确的 DNS 查询。

NetLog 从 `chrome://net-export` 采集，选择脱敏模式，不启用包含 Cookie、凭据或原始字节的选项；即使如此日志仍仅在本机分析。操作依据见 [Google 官方 Chrome 网络故障日志说明](https://support.google.com/chrome/a/answer/6271171)。若改用无账号临时资料以减少账号背景流量，应记录为“等效启动参数测试”，不能冒充实际专属资料的完整流量观测。

**通过标准：** 专属 Chrome 未直接通过系统 DNS 或其自带安全 DNS 对外解析该测试域名；请求通过配置代理完成，或本地解析被限制。代理进程自行解析上游属于代理行为，不误判成浏览器旁路。loopback 回调解析除外。

若只有启动参数截图，没有有效对照或实际观测，记“待验”。不要为测试关闭代理的正常 DNS 功能，也不要导出含账号会话的完整 NetLog 到共享目录。

### B04：运行中代理退出与恢复

此项会短暂影响现有网络，仅在用户选择的维护窗口执行；其他阶段不停止日常代理。

1. 保持一个受管 CLI 和专属 Chrome 会话运行，记录正常请求成功。
2. 退出本地代理，确认 `<端口>` 确实不再监听；仅隐藏窗口不算退出代理。
3. 分别从运行中的 CLI、浏览器和 VS Code 面板发起**新请求**，再测试新启动入口。
4. 观察请求错误和客户端连接，确认没有新建直连；不能只用旧页面还能显示来判断联网成功。
5. 恢复原代理，确认 `claude-check` 通过，再验证正常请求恢复。

**通过标准：** 代理停止后，新入口阻断；运行中受管客户端的新请求失败，没有改用其他代理或直连。恢复后可重试或重启恢复，不需要改变节点。

代理仍在运行、但内部自行选择 DIRECT 的情况不属于“端口关闭”，本工具不能据此提供保护承诺。

### B05：Wi-Fi 切换与休眠唤醒

在维护窗口分别完成一次 Wi-Fi/热点切换和一次合盖休眠唤醒。记录切换/唤醒前后，以及代理尚未就绪时的状态。

**通过标准：** 未就绪时新入口被拒绝、已有会话的新请求失败；就绪且门禁通过后恢复。实际网络观察没有客户端绕过指定端口的新连接。若观察不到未就绪窗口，只能说明恢复成功，不能把该次测试当成窗口期阻断证据。

失败后恢复原网络和代理配置。不能用普通请求成功代替唤醒窗口期验证。

### B06：OAuth 专属浏览器与回调

在下一次确有登录需求时验证，不为了测试而注销正在使用的账号。由本人完成登录、双重验证和回调。

**通过标准：** 授权页面进入专属 Chrome，回调完成、CLI 可再次运行 A05。记录自动接管是否有效；若该版本只能手动复制授权链接，记录“手动路径通过、自动路径待修复/不支持”，不能记为自动接管成功。

OAuth 页面出现在日常浏览器时，不继续在该窗口登录；使用 `claude-web '完整授权链接'` 打开专属资料。测试记录中不保存完整链接、code、state 或 Token。

## 5. 验收报告与完成标准

每轮复制以下模板填写，原始证据保存在本机；可分享报告只保留脱敏摘要。

```text
验收日期/执行人：
脚本版本或文件摘要：
macOS / Chrome / VS Code / 官方扩展版本：
默认 CLI / npm CLI / native CLI 版本：
代理：127.0.0.1:<端口>
CLI 时区：<时区>
系统和浏览器时区：

编号 | 等级 | 结果 | 证据位置与时间 | 问题/复测
A01–A12：逐项填写，不合并成一条“全部正常”
B01–B06：逐项填写；缺测试条件记待验

P0 通过/失败/待验数量：
P1 通过/失败/待验数量：
阻断问题：
已恢复原网络/代理状态：是/否/未改动
结论：未通过 / 核心配置验收通过 / 完整验收通过
```

**完成标准：** P0 全部通过且无未解决故障，可声明核心配置通过；P1 也全部完成且满足各项证据要求后，才声明完整验收通过。账号没有被限制、风险评分变绿、模型口头说正常，均不替代以上标准。

CLI、官方扩展、Chrome 或本套脚本升级后，重跑 A01–A09 及对应升级/故障回归；代理端口改变后，增加 B01/B04；网络策略或浏览器参数改变后，重跑 B02/B03。只有文档措辞修改时无需重复消耗模型额度。
