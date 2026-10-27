# GitHub 自动同步 · 配置步骤

目标：你改完飞书表格 → 网页**每小时自动更新**，不用再找我，也不用再扫码授权飞书。

全程约 20 分钟，分四段。**第 2 段（飞书自建应用）最容易卡住，先做它。**

---

## 第 0 段：先定一件事——仓库公开还是私有

这决定你的榜单数据会不会被外人看到，建仓库时就要选，建议先想清楚。

| | 公开仓库 | 私有仓库 |
|---|---|---|
| GitHub Pages（网页托管） | **免费** | 要付费账号（Pro $4/月） |
| Actions 额度 | 免费无限 | 2000 分钟/月（每天跑 2 次约用 180 分钟，**远远够**） |
| 榜单数据 | **任何人可见**，包括你的「剧单来源」渠道 | 只有你能看 |
| 网页能不能免费用 | 能 | 不能（Pages 要钱） |

> ⚠️ **一个必须先想清楚的事：自动更新的网址会变。**
> 现在的主链接 `workbuddy.link/p/U91GX2IR...` 是 WorkBuddy 平台内的发布页，
> 发一次要一个 30 分钟就过期的令牌，**只能人工发，外部定时任务发不了**。
> 所以一旦上自动更新，对外链接就变成 `https://<用户名>.github.io/drama-hit-finder/`。
> 想两者都要的话：GitHub 跑自动版给外部看，WorkBuddy 那个链接留着做内部完整版，我定期手动同步。

**我的建议：建公开仓库，但只往里放脱敏后的网页。**

具体做法：
- 公开仓库里只放**外部版数据**（剧名 / 语种 / 题材 / 剧场 / 推荐强度），不含「剧单来源」
- 内部完整版（带来源、热度分拆解、CSV 导出）继续用资料库发布页，我手动更新
- 这样免费、自动、且不泄露你的数据渠道

如果你觉得榜单数据本身就是行业公开信息、不敏感，**直接建公开仓库**最省事，一步到位。

---

## 第 1 段：注册 GitHub（5 分钟）

1. 打开 `https://github.com/signup`
2. 填邮箱 → 密码 → 用户名（**用户名记下来**，后面要给我）
3. 邮箱收验证码，填上
4. 那个「欢迎问卷」可以一路跳过
5. 注册完不用选付费方案，默认的 **Free** 就够

> 不用信用卡、不用实名。

---

## 第 2 段：建飞书自建应用（10 分钟，最容易漏步骤）

网页自动同步要用**应用身份**读飞书，不能用你个人的扫码登录（会过期）。

1. 打开 `https://open.feishu.cn/app`，用你的飞书账号登录
2. 右上角 **创建企业自建应用**
   - 名字随便，比如「剧目库同步」
   - 图标不用管
3. 左侧 **权限管理** → 搜索框输入 `sheets`
   - 勾选 **「查看、评论、编辑和管理电子表格」**（`sheets:spreadsheet:read`）
   - 点「批量开通」，有确认弹窗就确认
4. 左侧 **凭证与基础信息**
   - 复制 **App ID**（形如 `cli_xxxxxxxx`）
   - 复制 **App Secret**
5. 左侧 **版本管理与发布**
   - 点「创建版本」→ 版本号随便（1.0.0）→ 保存 → **申请发布**
   - 企业自建应用一般点完就生效，不用等审批
6. ⚠️ **最容易漏的一步，不做一定报权限错：**
   - 打开你那份飞书表格 `https://qcnvh9os52bb.feishu.cn/wiki/FE1iwsFjDi8IBfkzdS3cDsQInNg`
   - **不要点「分享」**——分享面板里搜不到应用，这是飞书的设计（已实测确认）
   - 正确入口：右上角 **「···」** → **「...更多」** → **「添加文档应用」**
   - 在弹窗里搜你刚建的应用名 → 权限选 **「可阅读」** → 添加
   - 找不到「更多」的话把浏览器窗口拉宽，或在菜单底部找折叠项

   **「添加文档应用」里也搜不到应用，只有三种原因（飞书官方明确要求）：**
   | 检查项 | 在哪看 |
   |---|---|
   | 应用没有**发布版本**（只在草稿态） | 开发者后台 → 版本管理与发布 → 创建版本 → 申请发布 |
   | 版本的**可用范围**不含你自己 | 同上，可用范围勾「全员」或至少包含你 |
   | 应用没开通**任何一个云文档 API 权限** | 权限管理里确认 `sheets:spreadsheet:read` 已生效 |

> 备注：这张表挂在**知识库（wiki）**里，不是普通云文档。知识库成员只能加人和群、加不了应用，
> 所以必须走「添加文档应用」这条路。加的是单篇文档权限，够用了。
> 表格的 spreadsheet_token 是 `Q3GgsvAIAhkrkCtH1JOctLJunrf`，加完权限不用改任何代码。

> App ID 和 App Secret **不要发给我**，你直接填进 GitHub Secrets（第 3 段）。少一个密钥过手。

---

## 第 3 段：建仓库 + 传代码（5 分钟）

### 3.1 建仓库

1. 登录 GitHub → 右上角 `+` → **New repository**
2. Repository name 填：`drama-hit-finder`
3. 可见性：按第 0 段的决定选 **Public** 或 **Private**
4. **不要**勾 "Add a README file"（我们本地已经有了）
5. 点 **Create repository**

### 3.2 把代码传上去（用命令行，最稳）

打开 Mac 的「终端」，逐行粘贴（把 `<你的用户名>` 换成实际用户名）：

```bash
cd /Users/killersu/WorkBuddy/2026-10-26-13-56-43

git init
# 注意带上 data/release_baseline.json —— 没有它，Actions 里的体检就没有对比基准（等于白关一道门）
git add .github scripts web GITHUB_SETUP.md .gitignore data/release_baseline.json
git commit -m "海外短剧爆款筛选器 - 初始版本"

git branch -M main
git remote add origin https://github.com/<你的用户名>/drama-hit-finder.git
git push -u origin main
```

执行 `git push` 时会弹 GitHub 登录窗口，按提示登录即可。
如果弹的是要你输密码，那是认证方式不对——去
`https://github.com/settings/tokens` → **Generate new token (classic)** →
只勾 `repo` → 生成后用这个 token 当密码粘贴。

### 3.3 填 Secrets（飞书凭证）

1. 进你刚建的仓库页面 → **Settings** 标签
2. 左侧 **Secrets and variables** → **Actions**
3. 点 **New repository secret**，加两个：

| Name | Secret |
|---|---|
| `LARK_APP_ID` | 第 2 段复制的 App ID |
| `LARK_APP_SECRET` | 第 2 段复制的 App Secret |

> 填进去之后 GitHub 会加密保存，连你自己都看不到了（只能覆盖）。

---

## 第 4 段：开 Pages + 跑第一次

1. 仓库页面 → **Settings** → 左侧 **Pages**
2. **Build and deployment** → Source 选 **GitHub Actions**（不是 "Deploy from a branch"）
3. 点 **Actions** 标签 → 左侧选「刷新短剧剧目库」
4. 右边点 **Run workflow** → 选 `main` 分支 → 绿色按钮确认
5. 等 1-2 分钟，看到绿色 ✅ 就成功了

成功之后，Actions 页面里能看到部署出的网址，形如：
`https://<你的用户名>.github.io/drama-hit-finder/`

**这就是你要发给别人的链接。** 之后**每天 08:17 和 20:17** 自动更新一次（北京时间）。
榜单是日更，跑更勤只是浪费额度，不会更快。

### 4.1 第一次跑完，核对三件事（很重要）

自动化最容易出的问题是「跑成功了，但数据是错的」。点开新链接看顶部：

| 看什么 | 应该是什么 |
|---|---|
| 覆盖剧目数 | **5545 部左右**（如果只有 4000 出头 → 拉错表了，拉成了剧场分表） |
| 数据截止日 | 跟你飞书里最新一期的日期对得上 |
| 随便点一部剧的「上新日期」 | 是正常日期，不是 `46200` 这种数字 |

三项都正常，就可以不再管它了。

---

## 出问题怎么查

点 Actions 里那次运行 → 看红色 ❌ 那一步的日志。

| 报错信息 | 原因 | 怎么修 |
|---|---|---|
| `飞书权限不足（code=9999166x）` | 漏了第 2 段第 6 步 | 把应用加为表格协作者 |
| `取 tenant_access_token 失败` | App ID / Secret 填错或没发布版本 | 检查 Secrets；确认应用已发布版本 |
| `xxx 拉取为空` | 表格结构变了（比如子表改名） | 告诉我，我改 `fetch_lark.py` 里的子表 ID |
| Pages 404 | Source 选成了 "Deploy from a branch" | 改回 **GitHub Actions** |
| 定时任务没跑 | GitHub 会延迟，也可能停用长期无活动的定时任务 | 手动点一次 Run workflow |

> 补充：GitHub 对**超过 60 天没有 commit** 的仓库会停用定时触发器。
> 如果你很久不手动改代码，定时任务可能悄悄停摆——偶尔去点一次 Run workflow 就能保持活跃。

---

## 已经写好的文件

| 文件 | 作用 |
|---|---|
| `.github/workflows/sync.yml` | 定时任务，每天 2 次 + 体检 + 部署到 Pages |
| `scripts/fetch_lark.py` | 用飞书 API 拉「数据底稿」（全量 7079 行，纯标准库，不依赖 lark-cli） |
| `scripts/build_library.py` | 清洗 + 打分 + 分级 |
| `scripts/check_release.py` | 发布前体检：剧目数暴跌等异常直接拦住，网页保持上一版 |
| `scripts/bundle_standalone.sh` | 打包成单文件网页 |
| `.gitignore` | 排除 17MB 原始数据，不进仓库 |

> 体检的基线在 `data/release_baseline.json`（几 KB，已设为例外会进仓库）。
> 它记录「上一次正常的数据长什么样」，Actions 每次拿新数据跟它比，异常就中止，坏数据不会上线。
