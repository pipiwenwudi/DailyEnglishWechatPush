"""
云端定时推送脚本 - GitHub Actions 使用
基于日期确定性选词，无需持久化状态
"""
import requests
import json
import os
from datetime import datetime, timedelta

SEND_KEY = os.environ.get("SEND_KEY", "SCT377109TSmQsjqaqPwDjTYWlt7wgWlLS")
WORD_POOL_FILE = "word_pool.json"

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


def get_day_seed():
    """基于日期生成确定性种子"""
    today = datetime.now()
    return today.year * 1000 + today.timetuple().tm_yday


def get_daily_words():
    """基于日期确定性选词，每天固定3个词"""
    pool = load_json(WORD_POOL_FILE, [])
    
    spoken_pool = [w for w in pool if w["type"] == "daily_spoken"]
    semi_pool = [w for w in pool if w["type"] == "semiconductor"]
    
    # 使用日期作为种子，确保每天选的词一样
    seed = get_day_seed()
    
    # 选口语词
    spoken_idx = [(seed + i * 7) % len(spoken_pool) for i in range(DAILY_SPOKEN_COUNT)]
    selected_spoken = [spoken_pool[i] for i in spoken_idx]
    
    # 选专业词
    semi_idx = (seed * 3 + 11) % len(semi_pool)
    selected_semi = [semi_pool[semi_idx]]
    
    # 计算学习进度（基于天数）
    total_days = len(spoken_pool) // DAILY_SPOKEN_COUNT
    current_day = seed % total_days + 1
    
    return selected_spoken, selected_semi, current_day, total_days


def build_morning_message():
    spoken_words, semi_words, current_day, total_days = get_daily_words()
    pool = load_json(WORD_POOL_FILE, [])
    total = len(pool)
    learned = current_day * (DAILY_SPOKEN_COUNT + SEMICONDUCTOR_COUNT)
    remaining = total - learned
    days_left = total_days - current_day

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
    msg += f"📊 **学习进度**：第 {current_day}/{total_days} 天\n\n"
    msg += f"🗓️ **本轮词库剩余可连续推送天数：{days_left}天**\n"
    return msg


def build_evening_message():
    """晚间复习消息"""
    # 使用前一天的词作为复习内容
    pool = load_json(WORD_POOL_FILE, [])
    yesterday_seed = get_day_seed() - 1
    
    spoken_pool = [w for w in pool if w["type"] == "daily_spoken"]
    semi_pool = [w for w in pool if w["type"] == "semiconductor"]
    
    spoken_idx = [(yesterday_seed + i * 7) % len(spoken_pool) for i in range(DAILY_SPOKEN_COUNT)]
    review_spoken = [spoken_pool[i] for i in spoken_idx]
    
    semi_idx = (yesterday_seed * 3 + 11) % len(semi_pool)
    review_semi = [semi_pool[semi_idx]]

    msg = "# 🔁 今日遗忘曲线复习清单\n\n---\n\n"
    msg += "## 🌤️ 日常口语复习\n\n"
    for i, w in enumerate(review_spoken, 1):
        msg += f"### {i}. 【单词】{w['word']} | {w['phonetic']}\n"
        msg += f"**中文释义**：{w['explain']}\n"
        msg += f"✅ 使用场景：{w['scene']}\n"
        msg += f"📝 英文原句：{w['sentence_en']}\n"
        msg += f"💡 中文翻译：{w['sentence_cn']}\n"
        msg += f"🔄 复习轮次：第 1 轮\n\n"

    msg += "---\n\n"
    msg += "## ⚙️ 半导体专业词汇复习\n\n"
    for i, w in enumerate(review_semi, 1):
        msg += f"### {i}. 【单词】{w['word']} | {w['phonetic']}\n"
        msg += f"**行业释义**：{w['explain']}\n"
        msg += f"✅ 应用场景：{w['scene']}\n"
        msg += f"📝 工程例句：{w['sentence_en']}\n"
        msg += f"💡 中文翻译：{w['sentence_cn']}\n"
        msg += f"🔄 复习轮次：第 1 轮\n\n"

    msg += "---\n\n"
    msg += "💪 继续保持，每天进步一点点！\n"
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
