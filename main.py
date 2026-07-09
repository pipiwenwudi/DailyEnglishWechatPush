from flask import Flask, jsonify, request
import requests
import json
import random
import os
import shutil
import logging
from datetime import datetime, timedelta

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(
    filename=os.path.join(BASE_DIR, "app.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


def load_config():
    path = os.path.join(BASE_DIR, "config.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return {"send_key": "", "daily_spoken_count": 2, "semiconductor_count": 1, "review_intervals": [1, 2, 4, 7, 15]}


CONFIG = load_config()
SEND_KEY = CONFIG.get("send_key", "")
DAILY_SPOKEN_COUNT = CONFIG.get("daily_spoken_count", 2)
SEMICONDUCTOR_COUNT = CONFIG.get("semiconductor_count", 1)
REVIEW_INTERVALS = CONFIG.get("review_intervals", [1, 2, 4, 7, 15])

WORD_POOL_FILE = os.path.join(BASE_DIR, "word_pool.json")
PUSH_HISTORY_FILE = os.path.join(BASE_DIR, "push_history.json")
REVIEW_PLAN_FILE = os.path.join(BASE_DIR, "review_plan.json")
WORDBOOK_FILE = os.path.join(BASE_DIR, "english_wordbook.json")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")

os.makedirs(BACKUP_DIR, exist_ok=True)


def backup_file(file_path):
    if not os.path.exists(file_path):
        return
    basename = os.path.basename(file_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"{basename}.{timestamp}.bak")
    try:
        shutil.copy2(file_path, backup_path)
        backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.startswith(basename)])
        while len(backups) > 5:
            old = backups.pop(0)
            os.remove(os.path.join(BACKUP_DIR, old))
    except Exception as e:
        logger.warning(f"Backup failed for {basename}: {e}")


def load_json(file_path, default=None):
    if default is None:
        default = {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.info(f"File not found, creating default: {file_path}")
        save_json(file_path, default)
        return default
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in {file_path}: {e}")
        backup_path = file_path + ".corrupted"
        if os.path.exists(file_path):
            shutil.move(file_path, backup_path)
            logger.info(f"Corrupted file moved to {backup_path}")
        save_json(file_path, default)
        return default
    except Exception as e:
        logger.error(f"Failed to load {file_path}: {e}")
        return default


def save_json(file_path, data):
    backup_file(file_path)
    temp_file = file_path + ".tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_file, file_path)
        return True
    except Exception as e:
        logger.error(f"Failed to save {file_path}: {e}")
        if os.path.exists(temp_file):
            os.remove(temp_file)
        return False


def load_word_pool():
    return load_json(WORD_POOL_FILE, [])


def load_push_history():
    return load_json(PUSH_HISTORY_FILE, {"pushed_ids": []})


def save_push_history(data):
    return save_json(PUSH_HISTORY_FILE, data)


def load_review_plan():
    return load_json(REVIEW_PLAN_FILE, {"reviews": []})


def save_review_plan(data):
    return save_json(REVIEW_PLAN_FILE, data)


def load_wordbook():
    return load_json(WORDBOOK_FILE, [])


def save_wordbook(data):
    return save_json(WORDBOOK_FILE, data)


def get_progress():
    pool = load_word_pool()
    history = load_push_history()
    pushed_ids = set(history.get("pushed_ids", []))
    total = len(pool)
    learned = len(pushed_ids)
    remaining = total - learned if total > 0 else 0
    return total, learned, remaining


def get_daily_words():
    pool = load_word_pool()
    history = load_push_history()
    pushed_ids = set(history.get("pushed_ids", []))

    spoken_pool = [w for w in pool if w["type"] == "daily_spoken" and w["id"] not in pushed_ids]
    semi_pool = [w for w in pool if w["type"] == "semiconductor" and w["id"] not in pushed_ids]

    spoken_exhausted = len(spoken_pool) < DAILY_SPOKEN_COUNT
    semi_exhausted = len(semi_pool) < SEMICONDUCTOR_COUNT

    if spoken_exhausted or semi_exhausted:
        logger.info("Word pool exhausted, resetting entire push history for new cycle")
        history["pushed_ids"] = []
        save_push_history(history)
        spoken_pool = [w for w in pool if w["type"] == "daily_spoken"]
        semi_pool = [w for w in pool if w["type"] == "semiconductor"]

    selected_spoken = random.sample(spoken_pool, DAILY_SPOKEN_COUNT)
    selected_semi = random.sample(semi_pool, SEMICONDUCTOR_COUNT)

    selected = selected_spoken + selected_semi

    history = load_push_history()
    history["pushed_ids"].extend([w["id"] for w in selected])
    save_push_history(history)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    plan = load_review_plan()
    for word in selected:
        plan["reviews"].append({
            "id": word["id"],
            "type": word["type"],
            "word": word["word"],
            "phonetic": word["phonetic"],
            "explain": word["explain"],
            "scene": word["scene"],
            "sentence_en": word["sentence_en"],
            "sentence_cn": word["sentence_cn"],
            "learn_time": now,
            "review_round": 0,
            "next_review": (datetime.now() + timedelta(days=REVIEW_INTERVALS[0])).strftime("%Y-%m-%d"),
            "completed": False
        })
    save_review_plan(plan)

    logger.info(f"Selected words: {[w['id'] for w in selected]}")
    return selected_spoken, selected_semi


def get_today_review_words():
    plan = load_review_plan()
    today = datetime.now().strftime("%Y-%m-%d")
    review_spoken = []
    review_semi = []

    for item in plan.get("reviews", []):
        if item.get("completed", False):
            continue
        if item.get("next_review", "") == today:
            if item.get("type") == "daily_spoken":
                review_spoken.append(item)
            else:
                review_semi.append(item)

    return review_spoken, review_semi


def advance_review(word_id):
    plan = load_review_plan()
    for item in plan["reviews"]:
        if item["id"] == word_id and not item.get("completed", False):
            item["review_round"] += 1
            if item["review_round"] >= len(REVIEW_INTERVALS):
                item["completed"] = True
                item["next_review"] = None
            else:
                next_days = REVIEW_INTERVALS[item["review_round"]]
                item["next_review"] = (datetime.now() + timedelta(days=next_days)).strftime("%Y-%m-%d")
            break
    save_review_plan(plan)


def build_morning_message():
    spoken_words, semi_words = get_daily_words()
    pool = load_word_pool()
    history = load_push_history()
    pushed_ids = set(history.get("pushed_ids", []))
    total = len(pool)
    learned = len(pushed_ids)
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
    total, learned, remaining = get_progress()

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
    msg += f"📊 **学习进度**：已学 {learned}/{total} 词，剩余 {remaining} 词\n"

    return msg


def send_wechat_msg(text, title="📖 每日英语打卡"):
    push_url = f"https://sctapi.ftqq.com/{SEND_KEY}.send"
    params = {"text": title, "desp": text}
    try:
        res = requests.post(push_url, data=params, timeout=10)
        result = res.json()
        if result.get("code") == 0:
            logger.info("WeChat push succeeded")
            return True, "推送成功"
        logger.error(f"WeChat push failed: {result}")
        return False, result.get("error", "未知错误")
    except Exception as err:
        logger.error(f"WeChat push exception: {err}")
        return False, str(err)


@app.route("/")
def index():
    total, learned, remaining = get_progress()
    return jsonify({
        "status": "running",
        "progress": {"total": total, "learned": learned, "remaining": remaining},
        "endpoints": {
            "/push?type=morning": "早推送（新词）",
            "/push?type=evening": "晚推送（复习）",
            "/push": "默认推送（自动判断）",
            "/words": "查看全部词库",
            "/records": "查看学习记录",
            "/review": "查看今日复习",
            "/add?word=xxx&meaning=xxx": "手动添加单词",
            "/clear": "清空词库（POST）",
            "/reset-history?confirm=yes": "重置推送历史（POST）"
        }
    })


@app.route("/push")
def push():
    push_type = request.args.get("type", "auto")

    if push_type == "morning":
        message = build_morning_message()
        success, msg = send_wechat_msg(message, "📖 每日英语学习早报")
    elif push_type == "evening":
        message = build_evening_message()
        success, msg = send_wechat_msg(message, "🔁 今日遗忘曲线复习清单")
    else:
        hour = datetime.now().hour
        if hour < 14:
            message = build_morning_message()
            success, msg = send_wechat_msg(message, "📖 每日英语学习早报")
        else:
            message = build_evening_message()
            success, msg = send_wechat_msg(message, "🔁 今日遗忘曲线复习清单")

    return jsonify({"success": success, "message": msg, "content": message})


@app.route("/words")
def words():
    return jsonify(load_word_pool())


@app.route("/records")
def records():
    return jsonify(load_push_history())


@app.route("/review")
def review():
    plan = load_review_plan()
    today = datetime.now().strftime("%Y-%m-%d")
    today_review = [r for r in plan.get("reviews", []) if r.get("next_review") == today and not r.get("completed")]
    all_pending = [r for r in plan.get("reviews", []) if not r.get("completed")]
    return jsonify({"today": today_review, "all_pending": all_pending})


@app.route("/add")
def add():
    word = request.args.get("word", "").strip()
    meaning = request.args.get("meaning", "").strip()

    if not word or not meaning:
        return jsonify({"success": False, "message": "参数不完整，需要 word 和 meaning"}), 400

    wordbook = load_wordbook()
    for item in wordbook:
        if item.get("word", "").lower() == word.lower():
            return jsonify({"success": False, "message": f"单词 {word} 已存在"})

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    wordbook.append({"word": word, "meaning": meaning, "add_time": now})
    save_wordbook(wordbook)

    plan = load_review_plan()
    plan["reviews"].append({
        "id": f"M{len(plan['reviews'])+1:03d}",
        "type": "manual",
        "word": word,
        "phonetic": "",
        "explain": meaning,
        "scene": "手动添加",
        "sentence_en": "",
        "sentence_cn": "",
        "learn_time": now,
        "review_round": 0,
        "next_review": (datetime.now() + timedelta(days=REVIEW_INTERVALS[0])).strftime("%Y-%m-%d"),
        "completed": False
    })
    save_review_plan(plan)

    logger.info(f"Manual word added: {word}")
    return jsonify({"success": True, "message": f"成功添加: {word}，将按艾宾浩斯曲线复习"})


@app.route("/clear", methods=["POST"])
def clear():
    save_wordbook([])
    logger.info("Wordbook cleared")
    return jsonify({"success": True, "message": "单词本已清空（不影响词库和复习计划）"})


@app.route("/reset-history", methods=["POST"])
def reset_history():
    confirm = request.args.get("confirm", "")
    if confirm != "yes":
        return jsonify({
            "success": False,
            "message": "请添加 ?confirm=yes 参数确认重置，此操作将清空所有学习记录和复习计划"
        })

    save_push_history({"pushed_ids": []})
    save_review_plan({"reviews": []})
    logger.info("History and review plan reset")
    return jsonify({"success": True, "message": "推送历史和复习计划已重置"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
