# 在 Railway 上部署只读 usage API 后端

本文说明如何把 `usage api serve`（只读 HTTP API）部署到 Railway。镜像只负责准备
环境；登录各 CLI、配置账号、创建 API 令牌和启动 API 都由你通过 `railway ssh`
手动完成。镜像里不包含任何凭据、令牌或登录状态。

> **状态：** 仓库内的 `Dockerfile` 已在本地构建并做过容器冒烟（见 PLAN.md §15、§17），
> 但**尚未在真实 Railway 服务上部署验证**，也没有在容器里完成过任何真实登录或
> 已认证的 provider 读取。下面的 Railway 操作步骤来自官方文档（见文末来源），
> 不是已执行的验收记录。

## 镜像内容

| 组件 | 固定版本 | 安装方式 |
|---|---|---|
| Python | 3.12.16 | `python:3.12.16-slim-bookworm`，锁定多架构 OCI index digest；`.python-version` 使用同一版本 |
| uv | 0.13.6 | 从 digest 固定的 `ghcr.io/astral-sh/uv:0.13.6` 复制；`pyproject.toml` 拒绝其他 uv 版本 |
| 本项目 | 当前源码 | `uv sync --locked --no-dev`；构建依赖另有精确版本与 wheel SHA-256；安装到 `/app/.venv` |
| Node.js | 22.23.4 LTS | 官方 tarball，校验 SHA-256 |
| Claude Code | 2.1.308 | `docker/cli/package-lock.json` + `npm ci --ignore-scripts`；直接链接锁定的 Linux 原生二进制 |
| Codex CLI | 0.165.0 | 同一 CLI 锁文件 + `npm ci --ignore-scripts`，保留官方启动器与平台包 |
| Grok Build CLI | 1.0.70 | 官方安装脚本所用的同一发布文件 `https://x.ai/cli/grok-1.0.70-linux-<arch>.gz`，校验 SHA-256 |
| 工具 | — | `curl` `ca-certificates` `git` `tmux` `procps` `less` `tini` |

说明：

- 三个 CLI 都装在 `/opt/usage-clis` / `/opt/grok`，命令链接到 `/usr/local/bin`，
  **不在** `HOME` 里。Railway 卷只在容器启动时挂载，不能遮住这些安装路径。
- Grok 官方安装方式是 `curl -fsSL https://x.ai/cli/install.sh | bash`，它会把二进制
  写进 `$HOME/.grok/bin`。为避开卷遮挡并固定版本，`Dockerfile` 直接下载安装脚本
  使用的同一版本化发布文件。xAI 没有公布校验和；`Dockerfile` 里的 SHA-256 是
  2026-10-29 下载时计算的（首次信任），发布文件一旦变化，构建会失败而不是静默接受。
- CLI 包装器及所有平台包由 `docker/cli/package-lock.json` 固定版本和 SHA-512。
  安装时不执行任何依赖生命周期脚本；Claude 的 postinstall 原本负责放置原生二进制，
  这里直接链接已校验的平台包。缺少当前架构的 Claude/Codex 二进制会使构建失败。
- 镜像设置 `DISABLE_AUTOUPDATER=1`（Claude Code）和 `GROK_DISABLE_AUTOUPDATER=1`
  （Grok），禁用后台自动升级；这不阻止用户手动运行更新命令。请通过审查后的重建升级，
  不要在运行中的容器里手动升级：Claude/Codex 修改 `docker/cli/package.json` 后在该目录
  运行 `npm install --package-lock-only --ignore-scripts` 并审查锁文件；Node/Grok 更新
  `Dockerfile` 的版本及两个架构的校验和；基础镜像同时更新版本标签和多架构 digest。
- `ENV HOME=/data/home`。入口脚本 `docker/entrypoint.sh` 在启动时以 `umask 077`
  创建 `HOME` 并设为 `0700`，然后执行 `CMD`（默认 `sleep infinity`）。`tini` 作为
  PID 1 负责转发信号和回收子进程。若 `/data` 不是挂载卷，入口脚本会打印警告。
- 容器以 root 运行。Railway 卷以 root 身份挂载，`railway ssh` 进入的也是 root。
- Railway 网页 console 打开的登录 shell 不继承镜像 `ENV`：`HOME` 来自 `/etc/passwd`
  （`/root`），`PATH` 被 `/etc/profile` 重置，导致 `usage: command not found`。镜像把
  `docker/shell-env.sh` 装为 `/etc/usage-api-shell-env.sh` 并从 `/etc/bash.bashrc` 加载，
  交互式 bash 会恢复 `HOME=/data/home`、把 `/app/.venv/bin`、`/opt/grok/bin` 加回
  `PATH`，并设置 `umask 077`。

## CA 事件、版本锁定与更新

2026-10 的 [eMudhra 事件](https://bugzilla.mozilla.org/show_bug.cgi?id=2083449)
涉及 8 个弱私钥中间 CA，包括 TLS 与代码签名证书；还有 Sectigo 的交叉签名链。
**固定依赖版本不能替代证书验证修复，只移除一个 emSign 根也不能证明所有链都被拒绝。**
浏览器的撤销列表不会自动保护容器里的 Python、curl 或原生 CLI。

本仓库采用“审查后固定构建输入 + 安全更新下限”，不是永久冻结证书库：

| 验证层 | 当前基线与依据 |
|---|---|
| CPython `ssl` | **3.12.16**；[官方紧急发布](https://blog.python.org/2026/10/python-3152-31410-31318-31216-31118/)直接拒绝受影响中间 CA 密钥。旧的 3.12.15 pin 已替换；不能只看 OpenSSL 版本判断这一补丁。 |
| Python HTTPX / certifi | `uv.lock` 已固定 **certifi 2026.10.23**，高于[官方建议的 2026.10.19](https://discuss.python.org/t/information-for-python-users-regarding-emudhra-emsign-ca-certificate-security-incident/109576)。本项目 `verify=True, trust_env=False`，默认走 certifi + CPython `ssl`，不是单纯系统 CA。 |
| uv 自己的下载器 | 固定 **0.13.6**，包含 0.13.5 的 [rustls-webpki 修复](https://github.com/astral-sh/uv/releases/tag/0.13.5)，并[新增 Python 3.12.16 下载目录](https://github.com/astral-sh/uv/releases/tag/0.13.6)。它的 TLS 栈独立于 Python；更新 uv 不会自动修复已有解释器或虚拟环境。 |
| Debian 系统 CA / curl / git | 安装签名 Debian 仓库中的 `ca-certificates`，构建时要求 **`>=20250419~deb12u2`**（[Bookworm 安全更新](https://packages.debian.org/bookworm/ca-certificates)）。不把 apt 永久锁在旧证书包；此处不声称整个 OS 可逐字节复现。 |
| Node / npm | 保留 **22.23.4**，其[安全发布](https://nodejs.org/en/blog/release/v22.23.4/)包含受影响公钥拒绝逻辑；官方 tarball 的两架构 SHA-256 与前端镜像 digest 继续固定。 |

Python 包、隔离构建工具和 npm 完整依赖图继续由各自锁文件／hash 约束；不要改成
`pip install -U`、`npm install latest` 或未固定版本的 `npx` 部署。`pip` 还有自己内置的
certifi：若另行使用 pip，按 Python 官方公告升级到 **26.2.2+**，不能把更新项目的
certifi 当作更新 pip。当前项目安装使用 uv，不需要额外安装 pip。
实际检查发现 Python 基础镜像仍附带 pip **25.0.1**（不在应用 venv 内）；CPython
3.12.16 的 `ssl` 拒绝逻辑会保护它免受本次弱密钥攻击，但不等于其 vendored CA 已更新。
本项目不使用它安装依赖；若自行改用 pip，应先按上述公告升级。

三个第一方 CLI 是另一条边界：Claude Code 2.1.308 高于[研究者修复清单所列的 2.1.303](https://emudhra.we-have-a-problem.com/#developers)；
Codex 0.165.0 的源码依赖图包含已修复的 rustls-webpki，但原生程序还可能使用其他 TLS
路径；Grok 的版本和 TOFU hash 也不能证明它内置的验证器已修复。
**不把这些源码／版本线索当作三个打包 CLI 所有网络路径的已验证安全结论。**
不要把登录文件、令牌或认证头交给第三方证书测试站点。

### 重建与核验

1. 版本升级同时审查版本号、来源、镜像 index digest、下载 hash、锁文件和运行时选择文件；
   本地与 Docker 的 Python／uv 要同步更新。Node 在各云平台上的选择方式见
   [前端部署说明](../web/README.md#部署)，Railway Docker 构建不受平台自动检测的 Python／Node 版本控制。
2. CA／基础镜像更新必须重新构建并部署，不能只重启旧容器，也不能只执行 `update-ca-certificates`
   就声称修好了 certifi 或内置验证器。本地使用 `docker build --pull --no-cache -t usage-api-railway .`；
   Railway 重建时也应避免复用旧 apt 安装层，并检查实际构建日志。`--pull` 不会替你更新已固定的 digest。
3. 在**新容器**中核验版本，输出仅含版本和证书包路径：

   ```sh
   python --version
   uv --version
   node --version
   npm --version
   python -c 'import ssl, certifi; print(ssl.OPENSSL_VERSION); print(certifi.__version__); print(certifi.where())'
   dpkg-query -W ca-certificates openssl libssl3 curl
   claude --version
   codex --version
   grok --version
   ```

4. 用[研究者的无认证测试链](https://emudhra.we-have-a-problem.com/#check)分别检查实际使用的
   curl、Python HTTPX、Node／uv 路径，至少覆盖 emSign 和 AAA 交叉签名两种链，并先用正常
   HTTPS 站点确认网络可用。**必须观察到证书验证拒绝**；DNS 错误、超时或普通 HTTP 错误都不是修复证据。
   浏览器、curl 或某个 CLI 单项通过，不代表其他路径通过。仓库实际执行的证据与限制记录在 PLAN.md §17。
5. 更新后重新启动第 8 步的服务。卷不会因此丢失，但 tmux 进程和 session-only 凭据会消失。

不要用 `curl -k`、`verify=False`、`NODE_TLS_REJECT_UNAUTHORIZED=0`、关闭 npm `strict-ssl`
或 uv 的不安全主机选项消除错误；也不要 pin 上游站点的叶证书，正常换证会使它失效。
本项目不签发公网证书：Railway 入口 HTTPS 由平台维护，与容器**出站** TLS 是两件事。
自定义域名／自管源站／上传 CA 要另行检查；若确实使用受影响链，应更换并撤销旧证书。
没有发现泄露证据时不把所有项目密钥视为已泄露；有可疑拦截或凭据暴露证据时，再撤销相应会话与令牌。

## 只能使用文件型凭据

容器里**没有** OS keyring（Secret Service）。因此：

- 可用：**External Claude Code file**（`~/.claude/.credentials.json`）、
  **External Codex auth file**（`~/.codex/auth.json`）、**External Grok auth file**
  （`~/.grok/auth.json`）。这些文件由各官方 CLI 写在卷上的 `HOME` 里。
- 无法**持久保存**：**Claude Platform（Console session）** 以及任何手动密钥。CLI 的
  持久密钥存储要求受支持的 keyring，没有时会如实失败。
- **Claude Platform 余额只能用“一进程模式”**：`usage --api …` 让 TUI 和 API 运行在
  同一个进程、共用同一个调度器和快照。在这个 TUI 的账号管理（`a`）里添加 Claude
  Platform 账号并选择 **Session only — lost on exit**，这个 `sessionKey` 就只保存在该
  进程内存中，API 返回的就是 TUI 显示的同一份余额。代价见第 8 步。单独运行的
  `usage api serve` 是另一个进程，读不到任何 TUI 的 session-only 凭据。
- 本项目的读取进程从不刷新令牌。官方 CLI 只有在被运行时才会自己续期；在所查看的源码
  版本中（Claude Code 2.1.311/2.1.312 的 npm 包、Codex `a29c7b97` 与 `rust-v0.165.0`、
  grok-build `2bdd1d6`），三者都只在访问令牌**到期前约 5 分钟内**才续期。镜像固定的
  Claude Code 2.1.308 与 Grok 1.0.70 未逐一核对（见 PLAN.md §15.6 未知项）。无人使用的服务器上令牌会过期，API 会显示
  认证失败/过期诊断。请按第 9 步运行 `usage-keepalive` 让官方 CLI 自己续期；若仍失败，
  `railway ssh` 进去重新登录对应 CLI 即可，不需要重启 `serve`（凭据在每次读取时重新解析）。

## 部署步骤

### 1. 从仓库创建服务

1. 在 Railway 新建项目 → **Deploy from GitHub repo**，选择本仓库。
2. Railway 会自动使用仓库根目录的 `Dockerfile` 构建。
   仓库里的 `railway.json`（`builder: DOCKERFILE`）只是显式声明；Railway 已把
   Config as Code 标为弃用，**新服务不能再启用它**，旧服务只用到 2026-12-01。
   对新服务来说起作用的是根目录 `Dockerfile` 的自动识别，`railway.json` 被忽略也没关系。
3. 不要给这个服务配置 healthcheck 路径：容器默认只执行 `sleep infinity`，API 是你
   之后手动启动的，部署时没有任何端口在监听。

前端是**另一个**服务：在同一项目里再从本仓库创建一个服务，把 **Root Directory**
设为 `web`，它使用 `web/` 自己的 `Dockerfile`/`railway.json`（见
[web/README.md](../web/README.md)）。下面的步骤只针对后端服务（Root Directory 为仓库根目录）。

### 2. 挂载卷到 `/data`

在服务上添加 Volume，挂载路径填 **`/data`**。每个服务只能挂一个卷。
CLI 登录文件、`~/.config/cli-usage-api/accounts.json` 和 `api_tokens.json` 都在
`/data/home` 下，重新部署后仍然保留。没有卷时，每次重新部署都会丢失全部登录和账号。

### 3. 端口与公开域名

1. 在服务 **Variables** 中添加 `PORT=8787`（非秘密）。Railway 会向容器注入 `PORT`；
   固定它可以让目标端口和你手动启动时使用的端口一致。
2. 在 **Settings → Networking → Public Networking** 中 **Generate Domain**，
   目标端口（target port）设为 **8787**。部署时没有进程监听，Railway 无法自动探测，
   需要手动选择/填写。

### 4. 进入容器

在本地安装并登录 Railway CLI，在仓库目录执行 `railway link` 选中该项目/服务，然后：

```sh
railway ssh            # 需要先在 Railway 注册 SSH 公钥，首次运行会提示
```

也可以用 Railway 网页里服务的 console（不需要 SSH 公钥）。

进入后确认环境：

```sh
echo "$HOME"           # /data/home
usage --help
claude --version; codex --version; grok --version
```

**登录任何 CLI 之前，`echo "$HOME"` 必须输出 `/data/home`。** 如果输出 `/root` 或
`usage` 找不到（旧镜像的网页 console 会这样），先手动恢复，或重新部署当前镜像：

```sh
export HOME=/data/home PATH=/app/.venv/bin:/opt/grok/bin:$PATH
cd "$HOME"
```

在 `HOME=/root` 时登录的 CLI 会把凭据写到 `/root/.claude`、`/root/.codex`、`/root/.grok`：
它们不在卷上，重新部署就会丢失，本项目也读不到。修正 `HOME` 后重新登录，并删除
`/root` 下的这些目录（里面是登录凭据）。

建议在 `tmux` 里操作（`tmux new -s usage`），断线后用 `tmux attach -t usage` 回来。

### 5. 登录三个官方 CLI

所有登录都在交互终端里完成，令牌只写入 `HOME` 下各 CLI 自己的文件。不要把令牌、
cookie 或 API key 放进命令参数、环境变量或 Railway Variables。

**Claude Code：**

```sh
claude
# 在 Claude Code 里输入 /login，选择 Claude 订阅账号登录。
# 无浏览器环境会显示一个 URL：在本地浏览器打开、授权，再把页面给出的代码粘贴回终端。
# 登录完成后 /exit 退出。
ls -l ~/.claude/.credentials.json     # 应为 0600
```

**Codex CLI：** 先让 Codex 使用文件存储凭据（容器里没有 keyring），再用设备码登录：

`cli_auth_credentials_store` 必须是 TOML **顶层**键，也就是写在第一个 `[表头]`
之前。追加到文件末尾时，它会落进最后一个表（例如 `[mcp_servers.x]`）里而不生效，
单纯 `grep` 也会误以为已经配置好。先检查文件里是否已有这个键：

```sh
mkdir -p -m 700 ~/.codex
touch ~/.codex/config.toml && chmod 600 ~/.codex/config.toml
grep -n 'cli_auth_credentials_store' ~/.codex/config.toml
```

- **没有输出**：把它加到文件**开头**（不是末尾）：

  ```sh
  { printf 'cli_auth_credentials_store = "file"\n\n'; cat ~/.codex/config.toml; } \
    > ~/.codex/config.toml.new && mv ~/.codex/config.toml.new ~/.codex/config.toml
  ```

- **已有输出**：用编辑器（如 `vi ~/.codex/config.toml`）把那一行改成
  `cli_auth_credentials_store = "file"`，并确认它在第一个 `[` 开头的表头之前；若它在
  某个表下面，把它移到文件开头。

验证：下面的命令只打印第一个表头之前的这个键，必须正好输出一行
`cli_auth_credentials_store = "file"`：

```sh
awk '/^[[:space:]]*\[/{exit} /^[[:space:]]*cli_auth_credentials_store[[:space:]]*=/' ~/.codex/config.toml
```

然后用设备码登录：

```sh
codex login --device-auth
# 在本地浏览器打开显示的链接，登录 ChatGPT 账号并输入一次性代码。
ls -l ~/.codex/auth.json
```

登录成功后如果 `~/.codex/auth.json` **不存在**，说明这次登录没有使用文件存储（配置键
没有在顶层生效）：按上面的验证命令修正配置后重新 `codex login --device-auth`。

**Grok Build CLI：**

```sh
grok login --device-auth
# 在本地浏览器打开显示的链接并输入代码。
ls -l ~/.grok/auth.json
```

不要用 `XAI_API_KEY` 代替登录：API key 不能读取订阅用量。

### 6. 配置本项目的账号

```sh
usage accounts add --provider claude-subscription   # 选 External Claude Code file，引用填 default
usage accounts add --provider codex-subscription    # 选 External Codex auth file，引用填 default
usage accounts add --provider grok-subscription     # 选 External Grok auth file，并明确选择身份/scope
usage accounts list
```

这些命令需要 TTY，`railway ssh` 提供交互终端即可。不要用 CLI 添加 `claude-platform`
（没有 keyring 会失败）；它在第 8 步的 TUI 里以 session-only 方式添加。
无头 `serve` 只在启动时读取一次账号配置，修改账号后要重启它；一进程模式下在 TUI
里修改账号会立即反映到 API。

### 7. 创建 API 令牌

```sh
usage api token create --label web
```

令牌（`usk_` 开头）只打印**一次**，立即复制到前端登录框或你的密码管理器。
文件 `~/.config/cli-usage-api/api_tokens.json` 里只保存它的 SHA-256 哈希。

```sh
usage api token list          # 只显示 id、label、创建时间
usage api token revoke <id>   # 需要确认；正在运行的 serve 会在约 1 秒内发现文件变化并生效
```

没有任何令牌时，非 demo 的 `serve` 和 `usage --api` 都会拒绝启动。

### 8. 启动 API（推荐：一进程模式）

在 `tmux` 会话的一个窗口里运行：

```sh
usage --api --api-host 0.0.0.0 --api-port "$PORT" \
  --allow-origin https://<你的前端域名> \
  --trust-proxy --keepalive
```

这会在**同一个进程**里运行 TUI 仪表盘、只读 API 和 keepalive（第 9 步）。API 读取的
就是 TUI 显示的快照；TUI 里添加、修改、删除、启用/停用账号会立即反映到
`/api/v1/dashboard`。顶部横幅显示 `API 0.0.0.0:<端口> 令牌认证` 和
`keepalive …`；API 出错时 TUI 弹出通知而不会崩溃，uvicorn 不向终端输出任何日志。
端口被占用、没有令牌、没有登录文件或已有 keepalive 实例时，命令在进入 TUI 之前就
以普通错误退出。按 `Ctrl-b d` 脱离 tmux 后进程继续运行；按 `q` 或 `Ctrl-C` 退出会同时
停止 API、keepalive 和调度器。

**Claude Platform：** 在这个 TUI 里按 `a` → 添加 Claude Platform 账号 → 选择
Console session，阅读高敏感度警告后只粘贴 `sessionKey` 的值，存储方式选
**Session only — lost on exit**，再显式发现并选择组织。这样 API 就能返回 Claude
Platform 余额。代价（请确认可以接受）：

- **每次重启、重新部署或进程退出后都要重新输入**。账号元数据留在卷上的
  `accounts.json` 中，但密钥丢失，重启后该账号的凭据不可用、无法读取余额，需在账号管理里重新输入。
- 这是**高敏感度的 Console 账号会话**，等同于登录态，而不是受限的 API key。它保存在一台
  有公开域名的服务器的进程内存里；任何能 `railway ssh` 进入容器（或读取进程内存）的人
  都可能拿到它。API 本身只返回余额，不返回会话、引用或组织 ID。
- Console 会话会过期或被撤销；**keepalive 只续期 Claude Code / Codex / Grok 的官方 CLI
  登录文件，不覆盖 Console 会话**。过期后 TUI/API 显示认证错误，需要重新输入。
- 本项目移除账号或进程退出都不会撤销远端会话；不再使用时在 Console 网页登出。

替代方案（只需要文件型登录时）：仍可使用无头的
`usage api serve --host 0.0.0.0 --port "$PORT" --allow-origin https://<你的前端域名> --trust-proxy`，
再在另一个 tmux 窗口运行独立的 `usage-keepalive`，或直接给 `serve` 加 `--keepalive`
（日志会同时打印到标准输出）。无头 `serve` 不支持 Claude Platform。

参数说明（两种方式相同；一进程模式中名称为 `--api-host` / `--api-port`）：

- `--host 0.0.0.0`：Railway 要求监听所有地址，绑定 `127.0.0.1` 时外部无法访问。
- `--allow-origin`：前端的精确 origin（`https://` + 域名，不带路径/末尾斜杠），可重复。
  不配置时 curl 仍可使用，但其它 origin 的浏览器会被 CORS 拦截。
- `--trust-proxy`：失败认证限流按 `X-Forwarded-For` 最右侧条目识别客户端。
  Railway 论坛的版主回答称其边缘代理会覆盖 `X-Forwarded-For` / `X-Real-IP`，
  而不是追加调用者传入的值；这不是正式文档，也未在本项目的部署上验证。只在
  Railway 这类可信反向代理后面使用此选项；本地直连时不要加。
- 按 `Ctrl-b d` 脱离 tmux，进程继续运行。`Ctrl-C` 正常停止（退出码 0）。

验证：

```sh
curl -sS https://<你的后端域名>/healthz                 # {"status":"ok"}
curl -sS -i https://<你的后端域名>/api/v1/dashboard | head -1   # 无令牌应为 401
```

然后在前端登录页填后端地址 `https://<你的后端域名>` 和令牌即可（前端部署见
[web/README.md](../web/README.md)）。

### 9. 保持登录（推荐）

第 8 步的 `--keepalive` 已在同一进程里运行 keepalive（日志只写入
`~/.local/state/usage-keepalive/keepalive.log`；`ALERT` 行在 TUI 中显示为警告通知）。
可用 `--keepalive-cli codex`（可重复）限定范围、`--keepalive-claude-mode status|model`
选择 Claude 方式。也可以不加 `--keepalive`，另开一个 tmux 窗口（`Ctrl-b c`）运行独立的：

```sh
usage-keepalive
```

两种方式共用同一个单实例锁，不能同时运行。keepalive 读取各登录文件的令牌字段，只用于判断访问令牌是否存在和取得
**到期时间**（Claude `expiresAt`、Grok 各 scope 的 `expires_at`；Codex 需要在本地解码
访问令牌 JWT 的 `exp`，不验证签名），从不记录或打印令牌值，CLI 输出也全部丢弃。它在
到期前约 290 秒内调用官方 CLI，让 CLI 自己续期并重写自己的文件：

| CLI | 调用 | 模型请求 |
| --- | --- | --- |
| Codex | `codex doctor --json` | 无 |
| Grok | `grok sessions list -n 1` | 无 |
| Claude Code（默认 `--claude-mode hybrid`） | 先 `claude auth status`；到期时间没有前移时再 `claude -p … --model haiku --effort low --tools "" --max-turns 1` | 仅回退时一次极小的 Haiku 请求，消耗少量订阅额度 |

- 是否成功只看**重新读取文件后到期时间是否前移**，不看退出码。
- Grok 的每个 scope 分别观察：任一 scope 的到期时间前移即算成功。一次完整尝试后仍不
  前移的 scope（例如 CLI 已不再续期的旧 `accounts.x.ai` 条目）记为 stale、只记录一次
  `stale_scope_ignored`，之后不再参与排期。以下 scope 永不标为 stale：未指定 selector 的
  账号默认读取的 scope（唯一的 modern scope，没有时为 legacy），以及已启用、读取默认
  `~/.grok/auth.json`（或 `$GROK_HOME/auth.json`）并显式指定 selector 的 Grok 账号的那个
  scope。未指定 selector 的账号不额外保护任何 scope（例如只有一个 modern scope 时，
  过期的 legacy 会被标为 stale，不会反复失败告警）。一进程模式下在 TUI 里修改账号会
  立即更新这组 scope；独立的 `usage-keepalive` 启动时只读一次账号配置（无法读取时记录
  `accounts unavailable; no protected Grok scopes` 并继续，不保护任何显式 selector）。
  该 scope 的到期时间之后若发生变化，会重新参与排期。
- 停止（退出 TUI、Ctrl-C 停止 `serve` 或独立进程）时不再开始新的目标或命令，并杀掉
  正在运行的官方 CLI 命令的整个进程组；被中断的尝试既不算成功也不算失败（例如在
  `claude auth status` 期间退出不会再发起 Haiku 请求）。单实例锁只在工作线程真正返回
  之后才释放，日志在此时才写 `keepalive stopped`。
- 检查间隔 `--interval` 最大 240 秒（默认 60）；循环还会在每个续期窗口开始和退避
  到期时提前醒来。到期时间未知时运行一次，日志为 `ran_unknown_expiry`，之后每 24 小时一次。
- Claude Code 已知问题（[#105645](https://github.com/anthropics/claude-code/issues/105645)）：
  续期请求超过约 2 秒时 CLI 可能在保存前退出，下一次运行会清空凭据。因此每次调用前会把
  `.credentials.json` 备份为同目录 `0600` 的 `.credentials.json.keepalive-backup`（经唯一
  临时文件原子替换写入）。只有当命令结束后文件仍被清空或无法解析、并且自命令结束以来
  未被改动（inode、修改时间、大小一致）时才恢复；文件被删除视为 logout，不会恢复。
  续期成功后删除备份。**如果旧的 refresh token 已在服务端被消耗，备份也无法恢复登录**，
  此时需要手动 `/login`。
- 备份含 refresh token，与登录文件同等敏感。最终 ALERT 后备份会**保留**；手动 `/login`
  使登录文件重新可用后，keepalive 检测到变化会自动删除这个过期备份（也可以手动
  `rm ~/.claude/.credentials.json.keepalive-backup`）。
- 不要在同一个 HOME 上同时运行交互式 Claude Code 会话：恢复前的检查无法完全排除与
  另一个进程并发写入的竞争。
- 失败重试退避 30 s → 60 s → 2 min → 5 min → 10 min；仍失败则输出
  `ALERT manual login required` 并停止尝试，直到你重新登录（文件变化且可用后自动恢复，
  日志为 `recovered`）。若期间登录被别的途径续期（到期时间后移或已不在窗口内），退避计数也会清零。
- `--claude-mode status` 只用 `auth status`（不耗额度）；`--claude-mode model` 只用 Haiku。
  `--cli codex` 等可限定范围；默认处理所有存在登录文件的 CLI。同一时间只能运行一个实例。
- 不要在同一个 HOME 上同时进行交互式 CLI 会话：Codex 并发续期可能触发
  `refresh_token_reused`，需要重新登录。
- 依据（源码/文档/社区报告）与未知项记录在 PLAN.md §15；尚未在真实账号上验证。

## 运维注意

- **重新部署或重启服务会结束 `usage --api` / `serve` 和所有 tmux 会话**（`CMD` 只是
  `sleep infinity`）。卷上的登录、账号和令牌会保留，但需要再次 `railway ssh` 进去手动
  启动第 8 步（一进程模式还要重新输入 session-only 的 Claude Platform `sessionKey`）。
- 公开域名上只有 `/healthz` 无需认证；其余接口都需要 `Authorization: Bearer` 令牌。
  令牌泄露时用 `usage api token revoke` 撤销并新建。
- 卷里保存的是各官方 CLI 的登录凭据（相当于密码）。不要把卷内容复制到不可信位置，
  不要分享 `railway ssh` 访问权限。
- 移除本项目的账号不会删除官方 CLI 的登录文件，也不会撤销远端会话；需要时在各
  CLI 里执行 logout，或在对应网站撤销。
- `--debug-log` 写入的文件包含原始响应体，可能有个人信息；用完删除。

## 本地运行后端

不需要 Docker：

本仓库选择 Python **3.12.16**（`.python-version`）和 uv **0.13.6**；项目 API 的
`requires-python >=3.11` 是兼容性声明，不是旧补丁版本的安全承诺。0.13.6 才收录所选
Python 补丁的下载目录；已有 `.venv` 也需要确认实际解释器已切换，不能只更新锁文件。
不要退回旧版本或关闭 TLS 验证。

```sh
uv sync --locked
uv run usage api serve --demo --allow-origin http://localhost:5173   # 回环地址的 demo 可不配令牌
uv run usage api token create                                       # live 模式需要令牌
uv run usage api serve --allow-origin http://localhost:5173         # 默认 127.0.0.1:8787
```

也可以在本地用镜像试运行（只用于检查环境，不含任何登录）：

```sh
docker build -t usage-api-railway .
docker run --rm -it -v usage-data:/data usage-api-railway bash
```

## 来源（2026-10-29 查阅）

- Grok Build 安装与入门：<https://docs.x.ai/build/overview>；安装脚本
  <https://x.ai/cli/install.sh>（版本参数、`$HOME/.grok/bin`、发布文件命名）；
  稳定版指针 <https://x.ai/cli/stable>（当时为 `1.0.70`）
- Grok CLI 参考（`grok login --device-auth`）：<https://docs.x.ai/build/cli/reference>
- Grok 设置参考（`GROK_HOME` 默认 `~/.grok`，`GROK_DISABLE_AUTOUPDATER`）：
  <https://docs.x.ai/build/settings/reference>
- Claude Code 安装（原生安装器、npm 安装、版本固定、`DISABLE_AUTOUPDATER`）：
  <https://code.claude.com/docs/en/setup>
- Codex 认证（`codex login --device-auth`、`cli_auth_credentials_store`、
  `CODEX_HOME/auth.json`）：<https://developers.openai.com/codex/auth>
- Railway Dockerfile 构建：<https://docs.railway.com/builds/dockerfiles>
- Railway 卷（运行时挂载、root 身份、每服务一个卷）：<https://docs.railway.com/guides/volumes>
- Railway Config as Code（弃用说明、`railway.json` 字段）：
  <https://docs.railway.com/config-as-code>、<https://docs.railway.com/config-as-code/reference>
- Railway `PORT` 注入与 `0.0.0.0` 监听：
  <https://docs.railway.com/networking/troubleshooting/application-failed-to-respond>
- Railway 域名与目标端口：<https://docs.railway.com/networking/domains/working-with-domains>
- `railway ssh`：<https://docs.railway.com/cli/ssh>
- Railway 边缘代理头（论坛版主回答，非正式文档）：
  <https://station.railway.com/questions/which-client-address-headers-does-the-ra-fb9e36d7>
