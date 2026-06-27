# 苏州人社 · 每日信息速递

每日自动收集 **苏州人力资源和社会保障局** 官网及其微信公众号的 AI / 技能培训 / 创新创业 相关信息，汇总推送到飞书群。

## ✨ 功能

- 🏛️ **官网多栏目监控**：人社要闻、通知公告、区县动态、就业创业、人才人事
- 📱 **微信文章搜索**：通过搜狗微信搜索补充公众号内容
- 🔍 **智能过滤**：AI人工智能、技能培训、创新创业等关键词匹配，排除不相关内容
- 🚫 **去重推送**：内置缓存，避免重复发送已推送过的文章
- 📊 **每日报告**：JSON 格式报告自动保存
- 📤 **飞书推送**：消息卡片形式，分类展示
- ⏰ **定时执行**：cron-job.org → GitHub Actions，每天早上 8:30

## 📁 项目结构

```
Daily_suzhou_hr/
├── .github/workflows/
│   └── daily_suzhou_hr.yml    # GitHub Actions 工作流
├── scripts/
│   ├── daily_suzhou_hr.py     # 主程序
│   └── requirements.txt       # Python 依赖
├── output/                    # 输出目录（报告、缓存）
└── README.md                  # 本文件
```

## 🚀 部署步骤

### 1. 推送到 GitHub

```bash
# 在 GitHub 上创建新仓库（例如 yourname/Daily_suzhou_hr）
# 然后在本地执行
git init
git add .
git commit -m "初始提交：苏州人社信息速递"
git remote add origin https://github.com/yourname/Daily_suzhou_hr.git
git push -u origin main
```

### 2. 配置飞书 Webhook

1. 在飞书群中添加**自定义机器人**（群设置 → 群机器人 → 添加机器人 → 自定义机器人）
2. 复制 Webhook 地址（格式：`https://open.feishu.cn/open-apis/bot/v2/hook/xxx`）
3. 在 GitHub 仓库设置中添加 Secret：
   - 进入 Settings → Secrets and variables → Actions
   - 点击 **New repository secret**
   - Name: `FEISHU_WEBHOOK`
   - Value: 粘贴你的 Webhook 地址

### 3. 配置 GitHub Personal Access Token（给 cron-job.org 用）

1. 访问 https://github.com/settings/tokens
2. 点击 **Generate new token (classic)**
3. 设置：
   - Note: `cron-job-trigger`
   - Expiration: 选择 1 年或 No expiration
   - Scopes: 勾选 **`repo`**（完全控制私有仓库）或 `public_repo`（公开仓库）
4. 生成并**复制 Token**（只显示一次，请妥善保存）

### 4. 配置 cron-job.org

1. 访问 https://cron-job.org 并注册/登录
2. 点击 **Create Cronjob**
3. 填写配置：

   | 字段 | 值 |
   |------|-----|
   | **Title** | `苏州人社每日推送` |
   | **URL** | `https://api.github.com/repos/你的GitHub用户名/Daily_suzhou_hr/actions/workflows/daily_suzhou_hr.yml/dispatches` |
   | **Method** | `POST` |
   | **Headers** | 见下方说明 |
   | **Request body** | `{"ref":"main"}` |
   | **Schedule** | `Every day at 08:30` |
   | **Time zone** | `Asia/Shanghai` |

   **Headers 设置（添加两个）**：
   ```
   Authorization: Bearer 你的GitHub Personal Access Token
   Accept: application/vnd.github+json
   Content-Type: application/json
   ```

4. 点击 **Create** 保存

> ⚠️ **注意**：cron-job.org 免费版最小间隔是 5 分钟，但我们可以设置每天 8:30 执行一次。

### 5. 验证

- **手动触发测试**：在 GitHub 仓库页面，进入 Actions → `Suzhou HR Daily Dispatch` → `Run workflow` → 点击绿色按钮
- **查看日志**：Action 运行后点击查看输出日志
- **飞书检查**：查看群机器人是否收到消息卡片

## 🔧 配置说明

### 修改监控栏目

编辑 `scripts/daily_suzhou_hr.py` 中的 `SECTIONS` 列表：

```python
SECTIONS = [
    {"name": "人社要闻", "list_url": "...", "link_prefix": "...", "icon": "📰"},
    # 添加或删除栏目...
]
```

### 调整关键词

修改 `AI_KEYWORDS` 和 `SKILLS_KEYWORDS` 列表来定制过滤规则。
修改 `EXCLUDE_KEYWORDS` 来排除不相关内容。

### 添加微信公众号

编辑 `WECHAT_ACCOUNTS` 列表添加更多公众号名称。

## 📋 飞书消息示例

推送的消息卡片包含：
- 日期 + 统计概要
- 按分类展示的条目（带链接可直接点击跳转）
- 每条显示标题、日期、匹配关键词
- 底部数据来源说明

## 🔄 与 Daily_science 的区别

| 特性 | Daily_science | 本程序 |
|------|--------------|--------|
| 数据源 | 36氪 + Hacker News | 苏州人社局官网 + 微信 |
| 定时方式 | GitHub Actions schedule | cron-job.org 触发 |
| 过滤策略 | 按分类（AI/机器人/航天） | AI关键词 + 技能培训关键词 |
| 输出形式 | Word + PNG + 飞书 | 飞书消息卡片 + JSON报告 |

## 📝 License

MIT
