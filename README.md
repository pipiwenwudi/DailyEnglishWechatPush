# DailyEnglishWechatPush

企业微信每日英语推送服务，支持双向交互、艾宾浩斯复习。

## 功能特性

- 每天早8点推送新词（2口语+1专业）
- 每天晚8点推送复习（艾宾浩斯第1/2/4/7/15天）
- 企业微信双向交互，支持指令添加生词
- 词库300条，防重复推送，用完自动循环

## 文件结构

```
├── app.py                 # 主服务（Flask）
├── wecom_push.py          # 独立推送测试脚本
├── config.json            # 配置文件
├── word_pool.json         # 词库（300条）
├── push_history.json      # 推送历史
├── review_plan.json       # 复习计划
├── english_wordbook.json  # 手动添加的生词本
├── backups/               # 自动备份目录
└── app.log                # 运行日志
```

## 部署运行

```bash
pip install -r requirements.txt
python app.py
```

## API接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 服务状态 |
| `/push-morning` | GET | 早间新词推送 |
| `/push-evening` | GET | 晚间复习推送 |
| `/report-stats` | GET | 本周学习统计 |
| `/wecom-callback` | GET/POST | 企业微信消息回调 |

## 微信指令

| 指令 | 说明 |
|------|------|
| `add 单词:释义` | 添加生词 |
| `review` | 手动触发复习 |
| `reset` | 重置推送历史 |
| `help` | 查看指令说明 |

## 定时任务配置

在 cron-job.org 或其他定时服务中配置：

- 早推送：每天 08:00 调用 `/push-morning`
- 晚推送：每天 20:00 调用 `/push-evening`
- 周报：每周日 21:00 调用 `/report-stats`

## 企业微信配置

1. 在企业微信后台创建自建应用
2. 配置「接收消息」回调URL：`https://你的域名/wecom-callback`
3. 填入 Token 和 EncodingAESKey 到 config.json
4. 将服务器IP加入应用白名单
