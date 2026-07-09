# 云端自动推送设置指南

## 第一步：上传到 GitHub

1. 访问 https://github.com 创建新仓库，名称如 `DailyEnglishWechatPush`
2. 上传整个项目文件夹

## 第二步：设置 GitHub Secrets

1. 进入仓库 → Settings → Secrets and variables → Actions
2. 点击 "New repository secret"
3. 名称填 `SEND_KEY`
4. 值填你的 Server酱 SendKey: `SCT377109TSmQsjqaqPwDjTYWlt7wgWlLS`

## 第三步：启用 GitHub Actions

1. 进入仓库 → Actions
2. 点击 "I understand my workflows, go ahead and enable them"

## 完成！

每天自动推送：
- **早上8点**：推送新词（2口语+1专业）
- **晚上8点**：推送复习（艾宾浩斯曲线）

## 手动触发

进入 Actions → Daily English Push → Run workflow → 选择 morning 或 evening

## 查看推送记录

进入 Actions 可以查看每次推送的运行日志
