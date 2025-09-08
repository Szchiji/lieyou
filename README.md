# Lieyou (猎游) - Telegram 信誉评价机器人

一个基于 Telegram 的社区信誉评价系统，帮助用户建立信任关系。

## 功能特点

- 🔍 **信誉查询** - 在群组中通过 @username 查询用户信誉
- 👍 **评价系统** - 推荐或警告其他用户
- 📊 **排行榜** - 查看声望榜、避雷榜和人气榜
- 📈 **个人报告** - 生成详细的个人信誉报告
- ⚙️ **管理功能** - 标签管理、用户管理、广播消息
- 🛡️ **反作弊** - 自动检测刷分和报复行为

## 快速开始

### 1. 克隆项目
```bash
git clone https://github.com/Szchiji/lieyou.git
cd lieyou
```

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env 文件，填入您的配置信息
```

### 4. 初始化数据库
确保 PostgreSQL 已安装并运行，然后程序会自动创建所需的表。

### 5. 运行机器人
```bash
python main.py
```

## 使用方法

### 群组中使用
- `@username` - 查询用户信誉档案

### 私聊机器人
- `/start` - 开始使用机器人
- `/myreport` - 查看个人信誉报告
- `/cancel` - 取消当前操作

### 管理员命令
管理员可在私聊中访问管理面板，管理标签、用户和发送广播。

## 环境变量说明

- `BOT_TOKEN` - Telegram Bot Token
- `DB_*` - PostgreSQL 数据库配置
- `ADMIN_USER_ID` - 管理员的 Telegram ID
- `GROUP_ID` - (可选) 限制用户必须加入的群组

## 时间衰减算法

本系统使用指数衰减算法来计算信誉分数：
- 新评价权重更高，旧评价权重随时间递减
- 衰减系数 λ = 0.0038（约6个月半衰期）
- 公式：`weight = exp(-λ * days)`

## 项目结构

```
lieyou/
├── main.py                    # 主入口
├── database.py                # 数据库层
├── bot_handlers/              # 业务逻辑
│   ├── __init__.py
│   ├── start.py              # 启动命令
│   ├── common.py             # 通用功能
│   ├── menu.py               # 菜单系统
│   ├── reputation.py         # 核心评价系统
│   ├── leaderboard.py        # 排行榜
│   ├── report.py             # 个人报告
│   ├── admin.py              # 管理功能
│   ├── broadcast.py          # 广播功能
│   └── monitoring.py         # 监控系统
├── requirements.txt          # 依赖列表
├── .env.example              # 环境配置示例
└── README.md                 # 项目文档
```

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！
