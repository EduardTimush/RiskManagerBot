import json
import urllib.request
import urllib.parse
import urllib.error
import logging

TOKEN = ""   # token from BotFather
CHAT_ID = ""        # your chat_id

log = logging.getLogger('riskbot.telegram')

def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }).encode("utf-8")

    try:
        with urllib.request.urlopen(url, data=data, timeout=5) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        log.error("Telegram HTTP %s: %s", e.code, e.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        log.error("Telegram is not avalaible: %r", e)

