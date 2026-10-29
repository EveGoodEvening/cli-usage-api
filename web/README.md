# 用量面板（Web 前端）

`usage api serve` 的只读网页前端。它只调用 API 的 `GET` 接口查看用量，不能添加、修改或删除账号。前后端分离：本目录构建出纯静态文件，可以部署到 Vercel、Cloudflare 或 Railway；API 单独运行（本机或 Railway，见仓库根目录 README）。

技术栈：Vite 7 + React 18 + TypeScript，无 UI 框架，纯 CSS（浅色/深色）。依赖版本全部精确锁定，提交了 `package-lock.json`。

## 鉴权

- 登录页填写 **API 地址** 和 **API 令牌**（`usk_…`，在服务器上运行 `usage api token create` 获得，只显示一次）。
- 令牌只放在 `Authorization: Bearer` 请求头里，不会出现在 URL、Cookie 或日志里。
- 默认只保存在当前标签页（sessionStorage），关闭后需要重新输入；勾选“在这台设备上记住”才会写入 localStorage。退出会清除两处。
- 任何请求返回 401 都会清除令牌和已显示的数据并回到登录页。有效令牌不会收到 429：429 表示令牌未通过验证且本机已被限流，同样清除令牌和数据、回到登录页，并按 `Retry-After`（缺失时 60 秒）显示倒计时，倒计时结束前“连接”按钮保持禁用。
- 前端本身是公开的静态文件，真正的访问控制在 API：没有有效令牌就读不到任何数据。

## 本地开发

```bash
cd web
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
npm test               # vitest：格式化、存储/鉴权、API 客户端、指标语义
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
2. Framework 会识别为 Vite；`vercel.json` 已经设置构建命令、输出目录 `dist`、SPA 回退和安全响应头。
3. 可选：在 Project Settings → Environment Variables 里设置 `VITE_API_BASE_URL`。
4. 部署后把 `https://<项目>.vercel.app` 加到 API 的 `--allow-origin`。

### Cloudflare Pages

1. Workers & Pages → Create → Pages → 连接仓库。
2. **Root directory** 填 `web`，Build command 填 `npm run build`，Build output directory 填 `dist`。
3. 可选：设置环境变量 `VITE_API_BASE_URL`；如果构建环境的 Node 太旧，再设置 `NODE_VERSION=22`。
4. `public/_headers` 会随构建复制到 `dist/`，提供安全响应头。Pages 在没有 `404.html` 时自动把未知路径交给 `index.html`，所以 `_redirects` 里没有规则。
5. 把 `https://<项目>.pages.dev` 加到 API 的 `--allow-origin`。

### Cloudflare Workers（静态资源）

```bash
cd web
npm ci && npm run build
npx wrangler deploy      # 使用 wrangler.toml：assets 目录 dist，SPA 回退
```

`dist/_headers` 同样生效。部署后的来源是 `https://usage-web.<子域>.workers.dev`。

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

## 页面结构

参考 “One True SaaS Layout”：

| 区域 | 内容 |
| --- | --- |
| 左侧图标栏 | 概览、账号、诊断、设置；底部头像按钮用于退出。演示模式下图标栏右边缘有紫色标记。 |
| 侧边栏 | 顶部按服务筛选（全部账号 / Claude / Platform / Codex / Grok）；下面是账号列表：服务圆形标识、账号名、服务与读取状态、状态点。 |
| 顶部标签 | 概览 / 指标 / 赠款 / 原始 JSON，右侧是重新读取和主题切换。 |
| 主内容 | 标题与说明；三张摘要卡（用量最高的额度、下一次重置、账号状态；Console 账号显示总余额和赠款数）；逐账号用量列表；底部提示卡片和按钮。 |
| 右侧栏 | 新鲜度（页面读取、成功观察、下次重试）；额度环形图；读取状态与诊断；服务图例。宽度小于 1200px 时隐藏。 |
| 底栏 | 左：实时/DEMO 标记和 API 主机；右：版本、服务器时间、设置、退出。 |

宽度小于 800px 时侧边栏变成抽屉；375px 宽度下没有横向滚动。

## 数据呈现规则

与 TUI 保持一致：

- 未知就是 `—`，不会按 0 显示；缺失的必需指标也会列出并标为未知。
- 百分比按 API 给出的精确小数原样显示，不四舍五入、不截断；进度条只在绘制时限制到 100%，超出时显示红色旗标和“超额 +x%”。
- Grok 产品（GrokBuild / GrokChat）的 `share_percent` 只显示为“已用”，不推算剩余或重置；嵌套在已证明的共享池下面。没有共享池证明时汇总行叫“Grok 汇总”。
- 有额度但没有重置时间时显示“重置 — 未知”。倒计时到点显示“等待刷新”，不会自行清零。
- 金额按最小货币单位和小数位数精确显示，带币种；负数保留。赠款到期不等于周期重置；不完整的读取显示 `≥N` 或 `—` 个赠款，不显示 0。
- 余额明细与总额不一致（`balance_mismatch`）时，诊断和总余额说明都会显示。
- 上次已知（`last_known`）和已过期（`stale`）的数值会变淡并带标记，不会被当成最新值。
