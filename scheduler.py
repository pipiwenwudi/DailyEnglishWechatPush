"""
云端定时推送脚本 - GitHub Actions 使用
无需 Flask，直接调用 Server酱 API
"""
import requests
import json
import random
import os
from datetime import datetime, timedelta

SEND_KEY = os.environ.get("SEND_KEY", "SCT377109TSmQsjqaqPwDjTYWlt7wgWlLS")
WORD_POOL_FILE = "word_pool.json"
PUSH_HISTORY_FILE = "push_history.json"
REVIEW_PLAN_FILE = "review_plan.json"

DAILY_SPOKEN_COUNT = 2
SEMICONDUCTOR_COUNT = 1
REVIEW_INTERVALS = [1, 2, 4, 7, 15]


def load_json(file_path, default=None):
    if default is None:
        default = {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default


def save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_daily_words():
    pool = load_json(WORD_POOL_FILE, [])
    history = load_json(PUSH_HISTORY_FILE, {"pushed_ids": []})
    pushed_ids = set(history.get("pushed_ids", []))

    spoken_pool = [w for w in pool if w["type"] == "daily_spoken" and w["id"] not in pushed_ids]
    semi_pool = [w for w in pool if w["type"] == "semiconductor" and w["id"] not in pushed_ids]

    if len(spoken_pool) < DAILY_SPOKEN_COUNT or len(semi_pool) < SEMICONDUCTOR_COUNT:
        history["pushed_ids"] = []
        save_json(PUSH_HISTORY_FILE, history)
        spoken_pool = [w for w in pool if w["type"] == "daily_spoken"]
        semi_pool = [w for w in pool if w["type"] == "semiconductor"]

    selected_spoken = random.sample(spoken_pool, DAILY_SPOKEN_COUNT)
    selected_semi = random.sample(semi_pool, SEMICONDUCTOR_COUNT)
    selected = selected_spoken + selected_semi

    history = load_json(PUSH_HISTORY_FILE, {"pushed_ids": []})
    history["pushed_ids"].extend([w["id"] for w in selected])
    save_json(PUSH_HISTORY_FILE, history)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    plan = load_json(REVIEW_PLAN_FILE, {"reviews": []})
    for word in selected:
        plan["reviews"].append({
            "id": word["id"], "type": word["type"], "word": word["word"],
            "phonetic": word["phonetic"], "explain": word["explain"],
            "scene": word["scene"], "sentence_en": word["sentence_en"],
            "sentence_cn": word["sentence_cn"], "learn_time": now,
            "review_round": 0,
            "next_review": (datetime.now() + timedelta(days=REVIEW_INTERVALS[0])).strftime("%Y-%m-%d"),
            "completed": False
        })
    save_json(REVIEW_PLAN_FILE, plan)

    return selected_spoken, selected_semi


def get_today_review_words():
    plan = load_json(REVIEW_PLAN_FILE, {"reviews": []})
    today = datetime.now().strftime("%Y-%m-%d")
    review_spoken, review_semi = [], []
    for item in plan.get("reviews", []):
        if item.get("completed") or item.get("next_review") != today:
            continue
        if item.get("type") == "daily_spoken":
            review_spoken.append(item)
        else:
            review_semi.append(item)
    return review_spoken, review_semi


def advance_review(word_id):
    plan = load_json(REVIEW_PLAN_FILE, {"reviews": []})
    for item in plan["reviews"]:
        if item["id"] == word_id and not item.get("completed"):
            item["review_round"] += 1
            if item["review_round"] >= len(REVIEW_INTERVALS):
                item["completed"] = True
                item["next_review"] = None
            else:
                item["next_review"] = (datetime.now() + timedelta(days=REVIEW_INTERVALS[item["review_round"]])).strftime("%Y-%m-%d")
            break
    save_json(REVIEW_PLAN_FILE, plan)


def build_morning_message():
    spoken_words, semi_words = get_daily_words()
    pool = load_json(WORD_POOL_FILE, [])
    history = load_json(PUSH_HISTORY_FILE, {"pushed_ids": []})
    total = len(pool)
    learned = len(set(history.get("pushed_ids", [])))
    remaining = total - learned
    days_left = remaining // (DAILY_SPOKEN_COUNT + SEMICONDUCTOR_COUNT)

    msg = "# 📖 每日英语学习早报\n\n---\n\n"
    msg += "## 🌤️ 模块一：日常口语用语（生活实用）\n\n"
    for i, w in enumerate(spoken_words, 1):
        msg += f"### {i}. 【单词】{w['word']} | {w['phonetic']}\n"
        msg += f"**中文释义**：{w['explain']}\n"
        msg += f"✅ 使用场景：{w['scene']}\n"
        msg += f"📝 英文原句：{w['sentence_en']}\n"
        msg += f"💡 中文翻译：{w['sentence_cn']}\n\n"

    msg += "---\n\n"
    msg += "## ⚙️ 模块二：半导体专业词汇（芯片行业）\n\n"
    for i, w in enumerate(semi_words, 1):
        msg += f"### {i}. 【单词】{w['word']} | {w['phonetic']}\n"
        msg += f"**行业释义**：{w['explain']}\n"
        msg += f"✅ 应用场景：{w['scene']}\n"
        msg += f"📝 工程例句：{w['sentence_en']}\n"
        msg += f"💡 中文翻译：{w['sentence_cn']}\n\n"

    msg += "---\n\n"
    msg += f"📊 **学习进度**：已学 {learned}/{total} 词，剩余 {remaining} 词\n\n"
    msg += f"🗓️ **本轮词库剩余可连续推送天数：{days_left}天**\n"
    return msg


def build_evening_message():
    review_spoken, review_semi = get_today_review_words()
    pool = load_json(WORD_POOL_FILE, [])
    history = load_json(PUSH_HISTORY_FILE, {"pushed_ids": []})
    total = len(pool)
    learned = len(set(history.get("pushed_ids", [])))

    msg = "# 🔁 今日遗忘曲线复习清单\n\n---\n\n"
    if review_spoken:
        msg += "## 🌤️ 日常口语复习\n\n"
        for i, w in enumerate(review_spoken, 1):
            msg += f"### {i}. 【单词】{w['word']} | {w['phonetic']}\n"
            msg += f"**中文释义**：{w['explain']}\n"
            msg += f"✅ 使用场景：{w['scene']}\n"
            msg += f"📝 英文原句：{w['sentence_en']}\n"
            msg += f"💡 中文翻译：{w['sentence_cn']}\n"
            msg += f"🔄 复习轮次：第 {w['review_round'] + 1} 轮\n\n"
            advance_review(w["id"])
    if review_semi:
        msg += "---\n\n"
        msg += "## ⚙️ 半导体专业词汇复习\n\n"
        for i, w in enumerate(review_semi, 1):
            msg += f"### {i}. 【单词】{w['word']} | {w['phonetic']}\n"
            msg += f"**行业释义**：{w['explain']}\n"
            msg += f"✅ 应用场景：{w['scene']}\n"
            msg += f"📝 工程例句：{w['sentence_en']}\n"
            msg += f"💡 中文翻译：{w['sentence_cn']}\n"
            msg += f"🔄 复习轮次：第 {w['review_round'] + 1} 轮\n\n"
            advance_review(w["id"])
    if not review_spoken and not review_semi:
        msg += "## 今日无复习任务\n\n"
        msg += "今天没有需要复习的单词，继续保持学习！\n\n"
    msg += "---\n\n"
    msg += f"📊 **学习进度**：已学 {learned}/{total} 词，剩余 {total - learned} 词\n"
    return msg


def send_server_chan(content, title="📖 每日英语打卡"):
    push_url = f"https://sctapi.ftqq.com/{SEND_KEY}.send"
    params = {"text": title, "desp": content}
    try:
        res = requests.post(push_url, data=params, timeout=10)
        result = res.json()
        if result.get("code") == 0 or result.get("errno") == 0:
            print(f"✅ 推送成功: {title}")
            return True
        print(f"❌ 推送失败: {result}")
        return False
    except Exception as e:
        print(f"❌ 推送异常: {e}")
        return False


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "morning"
    
    if mode == "morning":
        msg = build_morning_message()
        send_server_chan(msg, "📖 每日英语学习早报")
    elif mode == "evening":
        msg = build_evening_message()
        send_server_chan(msg, "🔁 今日遗忘曲线复习清单")
    else:
        print("用法: python scheduler.py [morning|evening]")
