import os
import json
import time
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def load_config():
    config_path = os.path.join(BASE_DIR, "wecom_config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)

CONFIG = load_config()
CORPID = CONFIG["WECOM_CORPID"]
CORPSECRET = CONFIG["WECOM_CORPSECRET"]
AGENTID = CONFIG["WECOM_AGENTID"]
TO_USER = CONFIG["WECOM_TO_USER"]
TOKEN_CACHE_FILE = os.path.join(BASE_DIR, CONFIG.get("TOKEN_CACHE_FILE", "wecom_token_cache.json"))

def get_access_token():
    if os.path.exists(TOKEN_CACHE_FILE):
        with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
        expire_time = cache.get("expire_time", 0)
        if time.time() < expire_time - 600:
            return cache["access_token"]

    url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
    params = {"corpid": CORPID, "corpsecret": CORPSECRET}
    resp = requests.get(url, params=params, timeout=10)
    data = resp.json()

    if data.get("errcode") != 0:
        raise Exception(f"获取access_token失败: {data}")

    token = data["access_token"]
    expires_in = data["expires_in"]

    cache = {
        "access_token": token,
        "expire_time": time.time() + expires_in
    }
    with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    return token

def send_markdown(content, max_retries=2):
    for attempt in range(max_retries + 1):
        try:
            token = get_access_token()
            url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
            payload = {
                "touser": TO_USER,
                "msgtype": "markdown",
                "agentid": AGENTID,
                "markdown": {
                    "content": content
                }
            }
            resp = requests.post(url, json=payload, timeout=10)
            result = resp.json()

            if result.get("errcode") == 0:
                print(f"[SUCCESS] 消息发送成功")
                return True, result
            else:
                print(f"[ERROR] 发送失败 (尝试 {attempt + 1}/{max_retries + 1}): {result}")
                if result.get("errcode") == 40014 or result.get("errcode") == 42001:
                    if os.path.exists(TOKEN_CACHE_FILE):
                        os.remove(TOKEN_CACHE_FILE)
                    print("[INFO] Token已过期，已清除缓存，下次将自动刷新")
                if attempt < max_retries:
                    time.sleep(2)
                    continue
                return False, result

        except requests.exceptions.RequestException as e:
            print(f"[ERROR] 网络异常 (尝试 {attempt + 1}/{max_retries + 1}): {e}")
            if attempt < max_retries:
                time.sleep(2)
                continue
            return False, {"errmsg": str(e)}

    return False, {"errmsg": "超过最大重试次数"}

def main():
    print(f"[INFO] 配置加载完成: CORPID={CORPID[:6]}..., AGENTID={AGENTID}, TO_USER={TO_USER}")
    print(f"[INFO] Token缓存文件: {TOKEN_CACHE_FILE}")

    test_content = """# 测试消息
> 企业微信推送测试

**状态**: 推送功能正常
**时间**: """ + time.strftime("%Y-%m-%d %H:%M:%S") + """

---

<font color="info">这是一条测试消息，如果你收到了说明配置正确！</font>"""

    print("[INFO] 开始发送测试消息...")
    success, result = send_markdown(test_content)

    if success:
        print("[INFO] 测试完成，推送功能正常")
    else:
        print(f"[ERROR] 测试失败，请检查配置: {result}")

if __name__ == "__main__":
    main()
