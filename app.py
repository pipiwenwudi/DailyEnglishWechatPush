"""
DailyEnglishWechatPush - 企业微信每日英语推送服务
Flask Web服务，支持定时推送、双向交互、艾宾浩斯复习
"""

import os
import json
import random
import time
import hashlib
import base64
import struct
import shutil
import logging
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from xml.etree import ElementTree as ET

# ==================== 初始化 ====================

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(
    filename=os.path.join(BASE_DIR, "app.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


# ==================== 配置加载 ====================

def load_config():
    path = os.path.join(BASE_DIR, "config.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return {}

CONFIG = load_config()
CORPID = CONFIG.get("WECOM_CORPID", "")
CORPSECRET = CONFIG.get("WECOM_CORPSECRET", "")
AGENTID = CONFIG.get("WECOM_AGENTID", 0)
TO_USER = CONFIG.get("WECOM_TO_USER", "@all")
CALLBACK_TOKEN = CONFIG.get("WECOM_CALLBACK_TOKEN", "")
AES_KEY = CONFIG.get("WECOM_AES_KEY", "")
BASE_URL = CONFIG.get("BASE_URL", "http://localhost:5001")
TOKEN_CACHE_FILE = os.path.join(BASE_DIR, CONFIG.get("TOKEN_CACHE_FILE", "wecom_token_cache.json"))
WORD_POOL_FILE = os.path.join(BASE_DIR, CONFIG.get("WORD_POOL_PATH", "word_pool.json"))
PUSH_HISTORY_FILE = os.path.join(BASE_DIR, CONFIG.get("PUSH_HISTORY_PATH", "push_history.json"))
REVIEW_PLAN_FILE = os.path.join(BASE_DIR, CONFIG.get("REVIEW_PLAN_PATH", "review_plan.json"))
WORDBOOK_FILE = os.path.join(BASE_DIR, CONFIG.get("WORDBOOK_PATH", "english_wordbook.json"))
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
DAILY_SPOKEN_COUNT = CONFIG.get("DAILY_SPOKEN_COUNT", 2)
SEMICONDUCTOR_COUNT = CONFIG.get("SEMICONDUCTOR_COUNT", 1)
REVIEW_INTERVALS = CONFIG.get("REVIEW_INTERVALS", [1, 2, 4, 7, 15])

os.makedirs(BACKUP_DIR, exist_ok=True)


# ==================== JSON文件读写（带备份） ====================

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
            os.remove(os.path.join(BACKUP_DIR, backups.pop(0)))
    except Exception as e:
        logger.warning(f"Backup failed for {basename}: {e}")


def load_json(file_path, default=None):
    if default is None:
        default = {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        save_json(file_path, default)
        return default
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in {file_path}: {e}")
        corrupted = file_path + ".corrupted"
        if os.path.exists(file_path):
            shutil.move(file_path, corrupted)
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


# ==================== 企业微信Token管理 ====================

def get_access_token():
    if os.path.exists(TOKEN_CACHE_FILE):
        with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
        if time.time() < cache.get("expire_time", 0) - 600:
            return cache["access_token"]

    url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
    resp = requests.get(url, params={"corpid": CORPID, "corpsecret": CORPSECRET}, timeout=10)
    data = resp.json()

    if data.get("errcode") != 0:
        raise Exception(f"获取access_token失败: {data}")

    cache = {
        "access_token": data["access_token"],
        "expire_time": time.time() + data["expires_in"]
    }
    with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    return data["access_token"]


# ==================== 企业微信消息加解密 ====================

class WXBizMsgCrypt:
    def __init__(self, token, encoding_aes_key, corp_id):
        self.token = token
        self.corp_id = corp_id
        self.key = base64.b64decode(encoding_aes_key + "=")

    def verify_url(self, msg_signature, timestamp, nonce, echostr):
        """校验URL，返回解密后的echostr"""
        import urllib.parse
        echostr = urllib.parse.unquote(echostr)
        sort_list = sorted([self.token, timestamp, nonce, echostr])
        sha1 = hashlib.sha1("".join(sort_list).encode()).hexdigest()
        if sha1 != msg_signature:
            return None
        return self._decrypt(echostr)

    def decrypt_msg(self, post_data, msg_signature, timestamp, nonce):
        """解密接收到的消息"""
        xml_tree = ET.fromstring(post_data)
        encrypt = xml_tree.find("Encrypt").text
        sort_list = sorted([self.token, timestamp, nonce, encrypt])
        sha1 = hashlib.sha1("".join(sort_list).encode()).hexdigest()
        if sha1 != msg_signature:
            logger.error("Signature verification failed")
            return None
        return self._decrypt(encrypt)

    def encrypt_msg(self, reply_msg, nonce, timestamp):
        """加密回复消息"""
        encrypt = self._encrypt(reply_msg)
        sort_list = sorted([self.token, timestamp, nonce, encrypt])
        sha1 = hashlib.sha1("".join(sort_list).encode()).hexdigest()
        return f"""<xml>
<Encrypt><![CDATA[{encrypt}]]></Encrypt>
<MsgSignature><![CDATA[{sha1}]]></MsgSignature>
<TimeStamp>{timestamp}</TimeStamp>
<Nonce><![CDATA[{nonce}]]></Nonce>
</xml>"""

    def _decrypt(self, text):
        aes = AESCipher(self.key)
        plain = aes.decrypt(base64.b64decode(text))
        content = plain[16:]
        msg_len = struct.unpack("!I", content[:4])[0]
        return content[4:4+msg_len].decode("utf-8")

    def _encrypt(self, text):
        text_bytes = text.encode("utf-8")
        random_str = os.urandom(16)
        msg_len = struct.pack("!I", len(text_bytes))
        plain = random_str + msg_len + text_bytes + self.corp_id.encode("utf-8")
        aes = AESCipher(self.key)
        return base64.b64encode(aes.encrypt(plain)).decode("utf-8")


class AESCipher:
    def __init__(self, key):
        self.key = key

    def encrypt(self, data):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend
        cipher = Cipher(algorithms.AES(self.key), modes.CBC(self.key[:16]), backend=default_backend())
        encryptor = cipher.encryptor()
        padded = self._pkcs7_pad(data)
        return encryptor.update(padded) + encryptor.finalize()

    def decrypt(self, data):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend
        cipher = Cipher(algorithms.AES(self.key), modes.CBC(self.key[:16]), backend=default_backend())
        decryptor = cipher.decryptor()
        plain = decryptor.update(data) + decryptor.finalize()
        return self._pkcs7_unpad(plain)

    def _pkcs7_pad(self, data):
        block_size = 32
        pad_len = block_size - (len(data) % block_size)
        return data + bytes([pad_len] * pad_len)

    def _pkcs7_unpad(self, data):
        pad_len = data[-1]
        return data[:-pad_len]


def parse_xml_content(xml_str):
    """解析XML消息体"""
    try:
        xml_tree = ET.fromstring(xml_str)
        msg = {}
        for child in xml_tree:
            msg[child.tag] = child.text
        return msg
    except Exception as e:
        logger.error(f"XML parse error: {e}")
        return None


# ==================== 企业微信消息发送 ====================

def send_markdown(content, max_retries=2):
    for attempt in range(max_retries + 1):
        try:
            token = get_access_token()
            url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
            payload = {
                "touser": TO_USER,
                "msgtype": "markdown",
                "agentid": AGENTID,
                "markdown": {"content": content}
            }
            resp = requests.post(url, json=payload, timeout=10)
            result = resp.json()

            if result.get("errcode") == 0:
                logger.info("WeChat push succeeded")
                return True, result

            logger.error(f"Push failed (attempt {attempt+1}): {result}")
            if result.get("errcode") in [40014, 42001]:
                if os.path.exists(TOKEN_CACHE_FILE):
                    os.remove(TOKEN_CACHE_FILE)
            if attempt < max_retries:
                time.sleep(2)
                continue
            return False, result

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error (attempt {attempt+1}): {e}")
            if attempt < max_retries:
                time.sleep(2)
                continue
            return False, {"errmsg": str(e)}

    return False, {"errmsg": "超过最大重试次数"}


def send_text(content, max_retries=2):
    """发送纯文本消息（用于指令回复）"""
    for attempt in range(max_retries + 1):
        try:
            token = get_access_token()
            url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
            payload = {
                "touser": TO_USER,
                "msgtype": "text",
                "agentid": AGENTID,
                "text": {"content": content}
            }
            resp = requests.post(url, json=payload, timeout=10)
            result = resp.json()
            if result.get("errcode") == 0:
                return True, result
            if attempt < max_retries:
                time.sleep(2)
                continue
            return False, result
        except Exception as e:
            logger.error(f"Send text error: {e}")
            if attempt < max_retries:
                time.sleep(2)
                continue
            return False, {"errmsg": str(e)}
    return False, {"errmsg": "超过最大重试次数"}


def send_news(title, description, detail_url, pic_url="", max_retries=2):
    """发送图文消息（推文）"""
    for attempt in range(max_retries + 1):
        try:
            token = get_access_token()
            url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
            payload = {
                "touser": TO_USER,
                "msgtype": "news",
                "agentid": AGENTID,
                "news": {
                    "articles": [{
                        "title": title,
                        "description": description[:512],
                        "url": detail_url,
                        "picurl": pic_url
                    }]
                }
            }
            resp = requests.post(url, json=payload, timeout=10)
            result = resp.json()

            if result.get("errcode") == 0:
                logger.info("News push succeeded")
                return True, result

            logger.error(f"News push failed (attempt {attempt+1}): {result}")
            if result.get("errcode") in [40014, 42001]:
                if os.path.exists(TOKEN_CACHE_FILE):
                    os.remove(TOKEN_CACHE_FILE)
            if attempt < max_retries:
                time.sleep(2)
                continue
            return False, result

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error (attempt {attempt+1}): {e}")
            if attempt < max_retries:
                time.sleep(2)
                continue
            return False, {"errmsg": str(e)}

    return False, {"errmsg": "超过最大重试次数"}


# ==================== 学习进度 ====================

def get_progress():
    pool = load_word_pool()
    history = load_push_history()
    pushed_ids = set(history.get("pushed_ids", []))
    total = len(pool)
    learned = len(pushed_ids)
    remaining = total - learned if total > 0 else 0
    return total, learned, remaining


# ==================== 每日选词逻辑 ====================

def get_daily_words():
    pool = load_word_pool()
    history = load_push_history()
    pushed_ids = set(history.get("pushed_ids", []))

    spoken_pool = [w for w in pool if w["type"] == "daily_spoken" and w["id"] not in pushed_ids]
    semi_pool = [w for w in pool if w["type"] == "semiconductor" and w["id"] not in pushed_ids]

    spoken_exhausted = len(spoken_pool) < DAILY_SPOKEN_COUNT
    semi_exhausted = len(semi_pool) < SEMICONDUCTOR_COUNT

    if spoken_exhausted or semi_exhausted:
        logger.info("Word pool exhausted, resetting for new cycle")
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


# ==================== 消息构建 ====================

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


def build_weekly_report():
    """生成本周学习统计周报"""
    pool = load_word_pool()
    history = load_push_history()
    plan = load_review_plan()
    pushed_ids = set(history.get("pushed_ids", []))

    total = len(pool)
    learned = len(pushed_ids)
    remaining = total - learned
    days_left = remaining // (DAILY_SPOKEN_COUNT + SEMICONDUCTOR_COUNT)

    today = datetime.now()
    week_start = today - timedelta(days=today.weekday())
    week_start_str = week_start.strftime("%Y-%m-%d")

    week_learned = 0
    week_reviewed = 0
    week_completed = 0

    for item in plan.get("reviews", []):
        learn_time = item.get("learn_time", "")
        if learn_time >= week_start_str:
            week_learned += 1
        if item.get("completed", False):
            week_completed += 1

    for item in plan.get("reviews", []):
        if item.get("next_review") and item.get("next_review", "") <= today.strftime("%Y-%m-%d"):
            if not item.get("completed", False):
                week_reviewed += 1

    spoken_count = len([w for w in pool if w["type"] == "daily_spoken"])
    semi_count = len([w for w in pool if w["type"] == "semiconductor"])
    spoken_learned = len([w for w in pool if w["type"] == "daily_spoken" and w["id"] in pushed_ids])
    semi_learned = len([w for w in pool if w["type"] == "semiconductor" and w["id"] in pushed_ids])

    msg = f"# 📊 本周学习统计周报\n\n---\n\n"
    msg += f"**统计周期**：{week_start_str} ~ {today.strftime('%Y-%m-%d')}\n\n"
    msg += f"## 📈 总体进度\n\n"
    msg += f"- 总词库：{total} 词（口语 {spoken_count} + 专业 {semi_count}）\n"
    msg += f"- 已学习：{learned} 词（口语 {spoken_learned} + 专业 {semi_learned}）\n"
    msg += f"- 剩余：{remaining} 词\n"
    msg += f"- 预计剩余推送天数：{days_left} 天\n\n"
    msg += f"## 📅 本周数据\n\n"
    msg += f"- 本周新学：{week_learned} 词\n"
    msg += f"- 已完成全部复习：{week_completed} 词\n\n"
    msg += "---\n\n"
    msg += f"💪 继续保持，每天进步一点点！"

    return msg


# ==================== 指令处理 ====================

def handle_add_command(content):
    """处理 add 单词:释义 指令"""
    parts = content.split(":", 1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        return "格式错误，请使用：add 英文单词:中文释义"

    word = parts[0].strip()
    meaning = parts[1].strip()

    wordbook = load_wordbook()
    for item in wordbook:
        if item.get("word", "").lower() == word.lower():
            return f"单词 {word} 已存在"

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
    return f"✅ 成功添加：{word} - {meaning}\n将按艾宾浩斯曲线（第1/2/4/7/15天）自动复习"


def handle_review_command():
    """处理 review 指令，手动触发复习"""
    review_spoken, review_semi = get_today_review_words()

    if not review_spoken and not review_semi:
        return "今日无复习任务，所有单词已复习完成！"

    msg = "# 🔁 手动复习推送\n\n---\n\n"

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

    total, learned, remaining = get_progress()
    msg += "---\n\n"
    msg += f"📊 **学习进度**：已学 {learned}/{total} 词，剩余 {remaining} 词\n"

    send_markdown(msg, "🔁 手动复习推送")
    return "✅ 已触发手动复习推送，请查看企业微信消息"


def handle_reset_command():
    """处理 reset 指令"""
    save_push_history({"pushed_ids": []})
    save_review_plan({"reviews": []})
    logger.info("History and review plan reset by user command")
    return "✅ 推送历史和复习计划已重置，词库将从头开始推送"


def handle_help_command():
    """处理 help 指令"""
    msg = """📖 每日英语学习 - 指令说明

可用指令：

1️⃣ add 英文单词:中文释义
   添加新单词到生词本，自动按艾宾浩斯曲线复习
   示例：add serendipity:意外发现美好事物的能力

2️⃣ review
   立即触发一轮手动复习推送

3️⃣ reset
   清空推送历史与复习计划，词库从头开始

4️⃣ help
   显示本指令说明

---
💡 每天早上8点自动推送新词，晚上8点推送复习"""
    return msg


# ==================== Flask路由 ====================

def render_morning_html(spoken_words, semi_words, total, learned, remaining, days_left, date):
    """渲染早报HTML详情页"""
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>每日英语学习早报 - {date}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 20px; }}
        .container {{ max-width: 600px; margin: 0 auto; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; text-align: center; }}
        .header h1 {{ font-size: 24px; margin-bottom: 5px; }}
        .header p {{ opacity: 0.9; font-size: 14px; }}
        .progress {{ background: #f8f9fa; padding: 15px 20px; border-bottom: 1px solid #eee; }}
        .progress-bar {{ background: #e9ecef; border-radius: 10px; height: 8px; margin-top: 8px; }}
        .progress-fill {{ background: linear-gradient(90deg, #28a745, #20c997); height: 100%; border-radius: 10px; transition: width 0.3s; }}
        .section {{ padding: 20px; }}
        .section-title {{ font-size: 18px; font-weight: 600; color: #333; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 2px solid #667eea; }}
        .word-card {{ background: #f8f9fa; border-radius: 8px; padding: 15px; margin-bottom: 12px; }}
        .word-header {{ display: flex; align-items: center; margin-bottom: 10px; }}
        .word-num {{ background: #667eea; color: white; width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; margin-right: 10px; }}
        .word-name {{ font-size: 18px; font-weight: 600; color: #333; }}
        .phonetic {{ color: #666; margin-left: 8px; font-size: 14px; }}
        .meaning {{ color: #333; margin-bottom: 8px; }}
        .scene {{ color: #28a745; font-size: 13px; margin-bottom: 8px; }}
        .example {{ color: #555; font-style: italic; margin-bottom: 4px; }}
        .translation {{ color: #888; font-size: 13px; }}
        .footer {{ background: #f8f9fa; padding: 15px 20px; text-align: center; color: #666; font-size: 13px; border-top: 1px solid #eee; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📖 每日英语学习早报</h1>
            <p>{date}</p>
        </div>
        <div class="progress">
            <div>学习进度：已学 {learned}/{total} 词，剩余 {remaining} 词</div>
            <div style="font-size: 12px; color: #666; margin-top: 4px;">本轮词库剩余可连续推送天数：{days_left}天</div>
            <div class="progress-bar"><div class="progress-fill" style="width: {learned*100//total}%"></div></div>
        </div>
        <div class="section">
            <div class="section-title">🌤️ 日常口语用语（生活实用）</div>"""

    for i, w in enumerate(spoken_words, 1):
        html += f"""
            <div class="word-card">
                <div class="word-header">
                    <div class="word-num">{i}</div>
                    <span class="word-name">{w['word']}</span>
                    <span class="phonetic">{w['phonetic']}</span>
                </div>
                <div class="meaning"><strong>中文释义</strong>：{w['explain']}</div>
                <div class="scene">✅ 使用场景：{w['scene']}</div>
                <div class="example">📝 {w['sentence_en']}</div>
                <div class="translation">💡 {w['sentence_cn']}</div>
            </div>"""

    html += """
        </div>
        <div class="section">
            <div class="section-title">⚙️ 半导体专业词汇（芯片行业）</div>"""

    for i, w in enumerate(semi_words, 1):
        html += f"""
            <div class="word-card">
                <div class="word-header">
                    <div class="word-num">{i}</div>
                    <span class="word-name">{w['word']}</span>
                    <span class="phonetic">{w['phonetic']}</span>
                </div>
                <div class="meaning"><strong>行业释义</strong>：{w['explain']}</div>
                <div class="scene">✅ 应用场景：{w['scene']}</div>
                <div class="example">📝 {w['sentence_en']}</div>
                <div class="translation">💡 {w['sentence_cn']}</div>
            </div>"""

    html += f"""
        </div>
        <div class="footer">
            DailyEnglishWechatPush · 每日英语学习
        </div>
    </div>
</body>
</html>"""
    return html


def render_evening_html(review_spoken, review_semi, total, learned, remaining, date):
    """渲染晚报HTML详情页"""
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>今日遗忘曲线复习清单 - {date}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 20px; }}
        .container {{ max-width: 600px; margin: 0 auto; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .header {{ background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); color: white; padding: 20px; text-align: center; }}
        .header h1 {{ font-size: 24px; margin-bottom: 5px; }}
        .header p {{ opacity: 0.9; font-size: 14px; }}
        .progress {{ background: #f8f9fa; padding: 15px 20px; border-bottom: 1px solid #eee; }}
        .section {{ padding: 20px; }}
        .section-title {{ font-size: 18px; font-weight: 600; color: #333; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 2px solid #f5576c; }}
        .word-card {{ background: #f8f9fa; border-radius: 8px; padding: 15px; margin-bottom: 12px; }}
        .word-header {{ display: flex; align-items: center; margin-bottom: 10px; }}
        .word-num {{ background: #f5576c; color: white; width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; margin-right: 10px; }}
        .word-name {{ font-size: 18px; font-weight: 600; color: #333; }}
        .phonetic {{ color: #666; margin-left: 8px; font-size: 14px; }}
        .meaning {{ color: #333; margin-bottom: 8px; }}
        .scene {{ color: #28a745; font-size: 13px; margin-bottom: 8px; }}
        .example {{ color: #555; font-style: italic; margin-bottom: 4px; }}
        .translation {{ color: #888; font-size: 13px; }}
        .review-round {{ background: #fff3cd; color: #856404; padding: 4px 8px; border-radius: 4px; font-size: 12px; display: inline-block; margin-top: 8px; }}
        .footer {{ background: #f8f9fa; padding: 15px 20px; text-align: center; color: #666; font-size: 13px; border-top: 1px solid #eee; }}
        .empty {{ text-align: center; padding: 40px; color: #666; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔁 今日遗忘曲线复习清单</h1>
            <p>{date}</p>
        </div>
        <div class="progress">
            <div>学习进度：已学 {learned}/{total} 词，剩余 {remaining} 词</div>
        </div>"""

    if not review_spoken and not review_semi:
        html += """
        <div class="empty">
            <p>今日无复习任务</p>
            <p>所有单词已复习完成！</p>
        </div>"""
    else:
        if review_spoken:
            html += """
        <div class="section">
            <div class="section-title">🌤️ 日常口语复习</div>"""
            for i, w in enumerate(review_spoken, 1):
                html += f"""
            <div class="word-card">
                <div class="word-header">
                    <div class="word-num">{i}</div>
                    <span class="word-name">{w['word']}</span>
                    <span class="phonetic">{w['phonetic']}</span>
                </div>
                <div class="meaning"><strong>中文释义</strong>：{w['explain']}</div>
                <div class="scene">✅ 使用场景：{w['scene']}</div>
                <div class="example">📝 {w['sentence_en']}</div>
                <div class="translation">💡 {w['sentence_cn']}</div>
                <div class="review-round">🔄 复习轮次：第 {w['review_round'] + 1} 轮</div>
            </div>"""
            html += """
        </div>"""

        if review_semi:
            html += """
        <div class="section">
            <div class="section-title">⚙️ 半导体专业词汇复习</div>"""
            for i, w in enumerate(review_semi, 1):
                html += f"""
            <div class="word-card">
                <div class="word-header">
                    <div class="word-num">{i}</div>
                    <span class="word-name">{w['word']}</span>
                    <span class="phonetic">{w['phonetic']}</span>
                </div>
                <div class="meaning"><strong>行业释义</strong>：{w['explain']}</div>
                <div class="scene">✅ 应用场景：{w['scene']}</div>
                <div class="example">📝 {w['sentence_en']}</div>
                <div class="translation">💡 {w['sentence_cn']}</div>
                <div class="review-round">🔄 复习轮次：第 {w['review_round'] + 1} 轮</div>
            </div>"""
            html += """
        </div>"""

    html += f"""
        <div class="footer">
            DailyEnglishWechatPush · 每日英语学习
        </div>
    </div>
</body>
</html>"""
    return html


@app.route("/")
def index():
    total, learned, remaining = get_progress()
    return jsonify({
        "status": "running",
        "service": "DailyEnglishWechatPush",
        "progress": {"total": total, "learned": learned, "remaining": remaining},
        "endpoints": {
            "GET /push-morning": "早间新词推送",
            "GET /push-evening": "晚间复习推送",
            "GET /report-stats": "本周学习统计周报",
            "GET /detail/morning/<date>": "早报详情页",
            "GET /detail/evening/<date>": "晚报详情页",
            "POST /wecom-callback": "企业微信消息回调"
        }
    })


@app.route("/detail/morning/<date>")
def detail_morning(date):
    """早报详情页"""
    pool = load_word_pool()
    history = load_push_history()
    pushed_ids = set(history.get("pushed_ids", []))
    total = len(pool)
    learned = len(pushed_ids)
    remaining = total - learned
    days_left = remaining // (DAILY_SPOKEN_COUNT + SEMICONDUCTOR_COUNT)

    spoken_words = [w for w in pool if w["type"] == "daily_spoken"][:DAILY_SPOKEN_COUNT]
    semi_words = [w for w in pool if w["type"] == "semiconductor"][:SEMICONDUCTOR_COUNT]

    return render_morning_html(spoken_words, semi_words, total, learned, remaining, days_left, date)


@app.route("/detail/evening/<date>")
def detail_evening(date):
    """晚报详情页"""
    total, learned, remaining = get_progress()
    review_spoken, review_semi = get_today_review_words()
    return render_evening_html(review_spoken, review_semi, total, learned, remaining, date)


@app.route("/push-morning", methods=["GET"])
def push_morning():
    """早间新词推送接口（图文消息）"""
    spoken_words, semi_words = get_daily_words()
    pool = load_word_pool()
    history = load_push_history()
    pushed_ids = set(history.get("pushed_ids", []))
    total = len(pool)
    learned = len(pushed_ids)
    remaining = total - learned
    days_left = remaining // (DAILY_SPOKEN_COUNT + SEMICONDUCTOR_COUNT)

    date = datetime.now().strftime("%Y-%m-%d")
    title = f"📖 每日英语学习早报 ({date})"

    desc_parts = []
    for w in spoken_words:
        desc_parts.append(f"{w['word']} {w['explain']}")
    for w in semi_words:
        desc_parts.append(f"{w['word']} {w['explain']}")
    description = "今日学习：" + " | ".join(desc_parts)

    detail_url = f"{BASE_URL}/detail/morning/{date}"
    success, result = send_news(title, description, detail_url)

    return jsonify({
        "success": success,
        "type": "morning",
        "message": "早间推送成功" if success else "推送失败",
        "detail_url": detail_url,
        "detail": result
    })


@app.route("/push-evening", methods=["GET"])
def push_evening():
    """晚间复习推送接口（图文消息）"""
    review_spoken, review_semi = get_today_review_words()
    total, learned, remaining = get_progress()

    date = datetime.now().strftime("%Y-%m-%d")
    title = f"🔁 今日遗忘曲线复习清单 ({date})"

    desc_parts = []
    if review_spoken:
        desc_parts.append(f"口语{len(review_spoken)}词")
    if review_semi:
        desc_parts.append(f"专业{len(review_semi)}词")

    if desc_parts:
        description = "今日复习：" + " + ".join(desc_parts)
    else:
        description = "今日无复习任务，继续保持学习！"

    detail_url = f"{BASE_URL}/detail/evening/{date}"
    success, result = send_news(title, description, detail_url)

    return jsonify({
        "success": success,
        "type": "evening",
        "message": "晚间推送成功" if success else "推送失败",
        "detail_url": detail_url,
        "detail": result
    })


@app.route("/report-stats", methods=["GET"])
def report_stats():
    """本周学习统计周报接口"""
    message = build_weekly_report()
    success, result = send_markdown(message, "📊 本周学习统计周报")
    return jsonify({
        "success": success,
        "type": "weekly_report",
        "message": "周报推送成功" if success else "推送失败",
        "detail": result
    })


@app.route("/wecom-callback", methods=["GET", "POST"])
def wecom_callback():
    """企业微信消息回调接口"""
    if request.method == "GET":
        msg_signature = request.args.get("msg_signature", "")
        timestamp = request.args.get("timestamp", "")
        nonce = request.args.get("nonce", "")
        echostr = request.args.get("echostr", "")

        logger.info(f"Callback verification request: signature={msg_signature}, timestamp={timestamp}, nonce={nonce}, echostr={echostr}")

        if not all([msg_signature, timestamp, nonce, echostr]):
            return "missing parameters", 400

        crypt = WXBizMsgCrypt(CALLBACK_TOKEN, AES_KEY, CORPID)
        echo = crypt.verify_url(msg_signature, timestamp, nonce, echostr)
        logger.info(f"Verification result: {echo}")
        if echo:
            return echo
        return "verification failed", 403

    if request.method == "POST":
        msg_signature = request.args.get("msg_signature", "")
        timestamp = request.args.get("timestamp", "")
        nonce = request.args.get("nonce", "")

        if not all([msg_signature, timestamp, nonce]):
            return "missing parameters", 400

        crypt = WXBizMsgCrypt(CALLBACK_TOKEN, AES_KEY, CORPID)
        post_data = request.data
        xml_str = crypt.decrypt_msg(post_data, msg_signature, timestamp, nonce)

        if not xml_str:
            return "decryption failed", 403

        msg = parse_xml_content(xml_str)
        if not msg:
            return "parse failed", 400

        msg_type = msg.get("MsgType", "")
        from_user = msg.get("FromUserName", "")

        if msg_type == "text":
            content = msg.get("Content", "").strip()
            reply = process_text_command(content)
            reply_xml = build_reply_xml(from_user, reply, timestamp, nonce, crypt)
            return reply_xml, 200, {"Content-Type": "application/xml"}

        return "success"


def process_text_command(content):
    """处理文本指令"""
    content_lower = content.lower().strip()

    if content_lower.startswith("add "):
        word_content = content[4:].strip()
        return handle_add_command(word_content)

    if content_lower == "review":
        return handle_review_command()

    if content_lower == "reset":
        return handle_reset_command()

    if content_lower == "help":
        return handle_help_command()

    return f"未知指令：{content}\n\n发送 help 查看可用指令"


def build_reply_xml(to_user, content, timestamp, nonce, crypt):
    """构建回复XML消息"""
    reply_msg = f"""<xml>
<ToUserName><![CDATA[{to_user}]]></ToUserName>
<FromUserName><![CDATA[{CORPID}]]></FromUserName>
<CreateTime>{int(time.time())}</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[{content}]]></Content>
</xml>"""
    return crypt.encrypt_msg(reply_msg, nonce, timestamp)


# ==================== 启动 ====================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
