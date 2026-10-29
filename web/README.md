# 用量面板（Web 前端）

`usage api serve` 的网页前端：查看各账号的用量；服务器允许写入时（默认允许，`--read-only` 或演示模式下不允许），也可以在网页上添加、编辑、停用、删除账号并调整顺序（见下文“账号管理”）。前后端分离：本目录构建出纯静态文件，可以部署到 Vercel、Cloudflare 或 Railway；API 单独运行（本机或 Railway，见仓库根目录 README）。

技术栈：Vite 7 + React 18 + TypeScript，无 UI 框架，纯 CSS（浅色/深色）。依赖版本全部精确锁定，提交了 `package-lock.json`。

Node.js 统一使用 **22.x，最低 22.23.4**；`package.json` 的 `>=22.23.4 <23`
限定主版本并允许托管平台继续发布安全补丁，`.npmrc` 的 `engine-strict` 会拒绝不匹配版本。
`web/.node-version` 为支持该文件的本地版本管理器及 Cloudflare 构建选择 **22.23.4**；
Docker 构建也固定为 **22.23.4**，静态服务器固定为 **Caddy 2.11.7**，
两个镜像都锁定多架构 OCI index digest。精确版本需要持续审查升级，不会自动获得安全修复。
`.npmrc` 禁止依赖的安装生命周期脚本，并保留平台可选包：esbuild / workerd 直接使用
锁定的本机二进制包，不运行 postinstall 下载器。使用 `npm ci`，不要用 `npm install`
替代部署安装；不要省略 optional dependencies，也不要跨操作系统或 CPU 架构复制 `node_modules`。

## 鉴权

- 登录页填写 **API 地址** 和 **API 令牌**（`usk_…`，在服务器上运行 `usage api token create` 获得，只显示一次）。
- 令牌只放在 `Authorization: Bearer` 请求头里，不会出现在 URL、Cookie 或日志里。
- 默认只保存在当前标签页（sessionStorage），关闭后需要重新输入；勾选“在这台设备上记住”才会写入 localStorage。退出会清除两处。
- 任何请求返回 401 都会清除令牌和已显示的数据并回到登录页。有效令牌不会收到 429：429 表示令牌未通过验证且本机已被限流，同样清除令牌和数据、回到登录页，并按 `Retry-After`（缺失时 60 秒）显示倒计时，倒计时结束前“连接”按钮保持禁用。
- 前端本身是公开的静态文件，真正的访问控制在 API：没有有效令牌就读不到任何数据。
- **令牌即写权限**：服务器没有用 `--read-only` 启动时，每个有效令牌都可以添加、修改和删除服务器上的账号。登录页的“记住”旁有同样的提醒；共享设备上不要记住令牌。

## 本地开发

```bash
cd web
# 先用支持 .node-version 的版本管理器安装/选择 Node 22.23.4
node --version          # 本地基线 v22.23.4；托管构建允许后续 22.x 补丁
npm ci

# 终端 1：后端演示模式（合成数据，本机回环地址可以不配置令牌）
usage api serve --demo --allow-origin http://localhost:5173

# 终端 2：前端
npm run dev            # http://localhost:5173 ，API 地址填 http://127.0.0.1:8787
```

如果后端已经创建过令牌，演示模式同样要求令牌。

不启动后端也可以开发界面：

```bash
npm run dev:mock       # VITE_MOCK=1，使用内置 DEMO 合成数据，令牌填任意值
```

`VITE_MOCK` 只用于开发。未设置时，生产构建里不包含演示数据或模拟客户端。

### 检查

```bash
npm run typecheck
npm run lint
npm test               # vitest：格式化、存储/鉴权、API 客户端、指标语义、账号表单与排序
npm run build          # 输出到 dist/
```

### 环境变量（构建时，均为公开值）

| 变量 | 作用 |
| --- | --- |
| `VITE_API_BASE_URL` | 登录页 API 地址的默认值，例如 `https://usage-api.up.railway.app`。不是密钥，会被编译进页面。 |
| `VITE_MOCK` | 仅开发使用，`1` 表示使用内置演示数据。部署时不要设置。 |

不要把令牌放进任何环境变量；令牌只在登录页输入。

## 后端需要允许前端来源

浏览器跨域访问 API 时，API 必须精确允许前端的来源（协议 + 域名 + 端口）：

```bash
usage api serve --host 0.0.0.0 --port "$PORT" --trust-proxy \
  --allow-origin https://usage-web.vercel.app
```

前端换了域名（例如绑定自定义域名）后，记得把新来源加到 `--allow-origin` 并重启 API。

## 部署

所有平台都会加上同一组安全响应头：严格的 Content-Security-Policy（只允许本站脚本/样式/字体；`connect-src https: http://localhost:* http://127.0.0.1:*`，因为 API 地址在运行时填写）、`frame-ancestors 'none'`、`X-Frame-Options: DENY`、`nosniff`、`Referrer-Policy: no-referrer`。线上 API 必须是 HTTPS；只有本机调试允许 http://localhost / 127.0.0.1。

### Vercel

1. 在 Vercel 导入这个仓库，**Root Directory** 选 `web`。
2. Framework 会识别为 Vite；`vercel.json` 已经设置 `npm ci`、构建命令、输出目录 `dist`、SPA 回退和安全响应头。`engines.node` 选择 22.x；Project Settings → Build and Deployment 中也选 22.x。Vercel **只选择主版本**，自动滚动次版本/补丁，不能冻结为 22.23.4；部署时确认实际构建 Node 版本不低于基线（可在 Build Command 临时加 `node --version &&`）。
3. 可选：在 Project Settings → Environment Variables 里设置 `VITE_API_BASE_URL`。
4. 部署后把 `https://<项目>.vercel.app` 加到 API 的 `--allow-origin`。

### Cloudflare Pages

1. Workers & Pages → Create → Pages → 连接仓库。
2. **Root directory** 填 `web`，Build command 填 `npm ci && npm run build`，Build output directory 填 `dist`。
3. 使用当前 v3 构建镜像，设置 `SKIP_DEPENDENCY_INSTALL=1`，避免平台先自动运行另一套依赖安装；Node 从提交的 `.node-version` 选择 22.23.4。删除旧 `NODE_VERSION` 覆盖值，或显式设为相同版本；v3 不读取 `package.json` 的 `engines` 来选择 Node。可选：设置公开环境变量 `VITE_API_BASE_URL`。
4. `public/_headers` 会随构建复制到 `dist/`，提供安全响应头。Pages 在没有 `404.html` 时自动把未知路径交给 `index.html`，所以 `_redirects` 里没有规则。
5. 把 `https://<项目>.pages.dev` 加到 API 的 `--allow-origin`。

### Cloudflare Workers（静态资源）

```bash
cd web
npm ci && npm run build
npm run deploy          # 使用锁定的本地 Wrangler 和 wrangler.toml，不通过 npx 下载新版本
```

`dist/_headers` 同样生效。部署后的来源是 `https://usage-web.<子域>.workers.dev`。

Wrangler **4.155.0** 是精确版本的开发依赖，完整依赖图及 SHA-512 在
`package-lock.json`。无凭据检查可运行
`WRANGLER_SEND_METRICS=false npm run deploy -- --dry-run`（先构建 `dist/`）；
这不代表已部署到 Cloudflare。升级时显式修改依赖版本并重新生成、审查锁文件；
Docker 镜像升级也必须同时更新标签与对应的多架构 digest，而不是移除 digest。

如果改用 Workers Builds 连接 Git 仓库，Root directory 同样设为 `web`，设置
`SKIP_DEPENDENCY_INSTALL=1`，Build command 用 `npm ci && npm run build`，
Deploy command 用 `npm run deploy`，避免默认 `npx wrangler deploy` 另行选择 CLI。
Workers Builds 也读取 `.node-version`；不要用 dashboard 的旧 `NODE_VERSION` 覆盖它。
`wrangler.toml` 的 `compatibility_date` 只选择 Workers API 行为，不是 Node 版本、
CA bundle 或安全补丁锁定；本项目只发布静态资源，没有 Node/Workers 服务端 API 代理。

### Railway

前端和 API 是两个独立的 Railway 服务。

1. 在同一个项目里 New Service → GitHub Repo，选择这个仓库。
2. Settings → **Root Directory** 设为 `/web`。Railway 会自动识别并使用 `web/Dockerfile` 构建，不需要（新服务也无法）设置 Config-as-code 路径。`web/railway.json`（`builder: DOCKERFILE`）只对仍支持配置文件的旧服务生效，被忽略也没关系（与 [docs/deploy-railway.md](../docs/deploy-railway.md) 一致）。
3. 可选：在 Variables 里设置 `VITE_API_BASE_URL`（Dockerfile 以构建参数读取，公开值）。
4. Networking → Generate Domain。Caddy 监听 Railway 提供的 `$PORT`，提供 SPA 回退和安全响应头。
5. 把生成的 `https://<服务>.up.railway.app` 加到 API 的 `--allow-origin`。

本机验证镜像：

```bash
docker build -t usage-web web
docker run --rm -p 127.0.0.1:8080:8080 usage-web
```

### eMudhra 事件：版本、证书信任与安全重建

2026-10 的事件涉及八个弱密钥中间 CA（另有 Sectigo 交叉签名链），不是应用依赖
版本冲突。只删除 eMudhra 根不能覆盖交叉签名；精确 npm 版本、锁文件完整性和 OCI
digest 只能固定拿到的字节，不能自动修复这些字节中的信任策略。

- **Node 构建/部署工具**：[Node 2026-10 安全公告](https://nodejs.org/en/blog/vulnerability/october-2026-security-releases)
  明确包含 eMudhra 修复；[22.23.4 发布记录](https://nodejs.org/en/blog/release/v22.23.4)
  包含 NSS 3.131.1 根更新和拒绝包含被封锁公钥的证书链。因此保留现有 Node 镜像版本与 digest，
  不为此次事件无依据升级。不要通过 `NODE_TLS_REJECT_UNAUTHORIZED=0`、关闭 npm `strict-ssl`
  或换成过期的 `NODE_EXTRA_CA_CERTS` / `NODE_OPTIONS` 信任覆盖来绕过证书错误。
- **Caddy 的实际边界**：本仓库 `Caddyfile` 关闭 `auto_https`，只在 `$PORT` 提供 HTTP 静态文件，
  不代理 API、不访问 HTTPS 上游；Railway 边缘终止浏览器 HTTPS。
  [Caddy 2.11.7 的官方 Linux amd64 SBOM](https://github.com/caddyserver/caddy/releases/download/v2.11.7/caddy_2.11.7_linux_amd64.sbom)
  显示其 Go 标准库为 **1.26.8**，本地镜像的 `caddy build-info` 也核实了这一点，不能声称已带此次 Go 修复。
  镜像内 `ca-certificates` / `ca-certificates-bundle` 已是 **20261020-r0**；这与二进制的 Go 版本是独立证据。
  [官方镜像配方](https://github.com/caddyserver/caddy-docker/blob/master/2.11/alpine/Dockerfile)
  下载发行版二进制；单更新镜像 OS CA 不会重编译 Go。当前只因 HTTP 静态服务边界保留原 pin；
  如启用 Caddy TLS、ACME 或 HTTPS 反代，必须先选择并核实使用
  [Go 1.26.10 / 1.27.3 或后续修复版本](https://groups.google.com/g/golang-announce/c/66pojueaQek)
  构建的 Caddy，连同 OS CA 一起审查，更新镜像标签/digest 后再使用，不能沿用本结论。
- **浏览器和云边缘**：页面执行和 API `fetch` 在用户浏览器中，使用浏览器/系统的证书验证，
  不是构建时 Node 或 Caddy 的信任库。更新并重启浏览器及系统，确保撤销信息生效；
  Vercel、Cloudflare、Railway 的边缘证书和边缘运行时由平台维护，仓库无法为它们锁定 CA。
  [Cloudflare 事件说明](https://blog.cloudflare.com/emudhra-certificate-compromise)
  记录 10-20 CDN/服务端 Zero Trust 缓解，但客户镜像、自带证书库和自定义信任配置仍需分别更新。
  Pages/Workers Builds 默认通过 `NODE_OPTIONS=--use-openssl-ca` 等变量使用构建镜像 OS CA，
  因此也要检查平台构建镜像及已有信任覆盖，不能只看 Node 版本。

重建前先更新本机 OS CA、浏览器、Docker Engine/CLI 及实际下载工具；不要在未经修复的
验证路径上下载替代证书或二进制。升级镜像时同时审查标签、所有目标架构和多架构 digest，
随后在仓库根目录运行 `docker build --pull --no-cache -t usage-web web`，重新部署并确认
新镜像已生效。`--pull --no-cache` **不会更新固定 digest 内的旧软件**，也不能代替修改过期 pin。
本地重新运行 `npm ci` 后构建；托管平台更新设置后清除旧构建缓存并重新部署，确认实际构建版本。
证书检查必须使用实际应用的验证路径，并区分证书拒绝与网络失败；浏览器或 curl 单个失败
都不是所有工具安全的证明。

一手参考：[Mozilla 事件记录](https://bugzilla.mozilla.org/show_bug.cgi?id=2083449)、
[研究者修复版本/交叉签名说明](https://emudhra.we-have-a-problem.com/)、
[Vercel Node 版本合同](https://vercel.com/docs/functions/runtimes/node-js/node-js-versions)、
[Pages 构建镜像/选择器/信任库](https://developers.cloudflare.com/pages/configuration/build-image/)、
[Workers Builds 镜像/选择器/信任库](https://developers.cloudflare.com/workers/ci-cd/builds/build-image/)。

## 页面结构

单栏布局，所有视图都在同一个居中的内容列里：

| 区域 | 内容 |
| --- | --- |
| 顶栏 | 产品名（演示模式带“演示”标记）、账号状态摘要、浏览器时区、**账号管理**按钮、重新读取、菜单（主题、连接信息、原始 JSON、退出）。 |
| 仪表盘（默认） | 按服务筛选（全部账号 / 需要留意 / 各服务）；逐账号分组列出指标行，点开行可看详情、赠款明细。多个账号重复的说明只在顶部说一次。 |
| 账号管理（`#accounts`） | 账号列表（拖动或键盘调整顺序、编辑、停用/启用、重新连接、删除）和添加/编辑表单。地址栏会变成 `#accounts`，浏览器“后退”回到仪表盘；Esc 由内到外依次取消拖动、关闭确认、关闭表单，最后回到仪表盘。 |

375px 宽度下没有横向滚动；窄屏时账号操作换到名称下方，服务选项排成 2×2。

## 账号管理

- **权限**：写操作使用登录时的同一个令牌，没有单独的写令牌。服务器用 `--read-only` 启动或处于演示模式时，页面显示只读提示，只能查看账号；任何写请求收到 `403 read_only` 时页面立即切换为只读，不会退出登录。
- **凭据只在请求正文里**：sessionKey、手动令牌和 API key 只通过 HTTPS 请求的 JSON 正文发送，从不进入 URL、浏览器存储、“原始 JSON”或日志；提交、取消、出错和离开表单时都会清空输入框。服务器从不回显已保存的凭据、自定义路径、Grok 范围标识或组织 ID。
- **登录文件**：可选“默认位置”或服务器上的绝对路径。路径必须以 `auth.json`（Claude 为 `.credentials.json`）结尾，文件需属于服务进程用户且权限为 0600；页面不会显示或上传文件内容。Grok 需要先“读取登录范围”并明确选择；Claude Platform 需要先“发现组织”并明确选择，即使只有一个组织也不会自动选中。
- **Console sessionKey**：输入框前显示高敏感度提醒（中英文）：只输入 sessionKey 的值，不要输入密码、完整 Cookie 请求头或 HAR 文件。
- **保存方式**：“加密保存到服务器系统密钥环”需要服务器有可用的加密密钥环（Railway 容器没有），保存失败时不会自动改用其他方式；“仅本次会话”只保存在服务器进程内存中，`usage api serve` 重启或重新部署后丢失，列表会显示“会话凭据已丢失”，编辑账号重新输入即可。
- **顺序**：拖动行首的 ⠿，或聚焦它后按 ↑ ↓ Home End（行内“移动”里也有上移/下移）。顺序保存在服务器的 `accounts.json`，仪表盘、TUI 和 `/api/v1/dashboard` 都按这个顺序显示；保存失败会恢复原顺序。
- **keepalive**：`--keepalive` 只维护服务启动时已经存在的默认登录文件；自定义路径不会被自动续期。之后在服务器上新登录的 CLI 需要重启服务才会被维护。
- **其他进程的修改**：在服务器上用 `usage accounts` 做的修改，会在下一次网页修改或重启 `usage api serve` 后生效；网页不会监视配置文件。

## 数据呈现规则

与 TUI 保持一致：

- 未知就是 `—`，不会按 0 显示；缺失的必需指标也会列出并标为未知。
- 百分比按 API 给出的精确小数原样显示，不四舍五入、不截断；进度条只在绘制时限制到 100%，超出时显示红色旗标和“超额 +x%”。
- Grok 产品（GrokBuild / GrokChat）的 `share_percent` 只显示为“已用”，不推算剩余或重置；嵌套在已证明的共享池下面。没有共享池证明时汇总行叫“Grok 汇总”。
- 有额度但没有重置时间时显示“重置 — 未知”。倒计时到点显示“等待刷新”，不会自行清零。
- 金额按最小货币单位和小数位数精确显示，带币种；负数保留。赠款到期不等于周期重置；不完整的读取显示 `≥N` 或 `—` 个赠款，不显示 0。
- 余额明细与总额不一致（`balance_mismatch`）时，诊断和总余额说明都会显示。
- 上次已知（`last_known`）和已过期（`stale`）的数值会变淡并带标记，不会被当成最新值。
