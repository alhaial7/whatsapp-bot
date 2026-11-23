import os, time, requests
from datetime import datetime, timedelta, timezone
from flask import Flask
import threading

# --- مفاتيحك من Render Environment ---
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
MY_NUMBER = os.getenv("MY_NUMBER") # مثال: 9665XXXXXXXX بدون +
ALPACA_KEY = os.getenv("ALPACA_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET")
FINNHUB_KEY = os.getenv("FINNHUB_KEY")

app = Flask(__name__)

# --- 1. فلتر الشرعية ---
# هذي قائمة مبدئية، تقدر تضيف عليها
HARAM_KEYWORDS = ["BANK", "CASINO", "ALCOHOL", "WEED", "CANNABIS", "TOBACCO", "LENDING"]
# قائمة الأسهم اللي نعرف انها حلال من متابعتنا - تقدر تزيدها
HALAL_WATCHLIST = ["INO","SOBR","SPRC","VIVS","JTAI","NESR","KVUE","AAPL","MSFT","NVDA","TSLA","AMD"]

def is_halal(symbol, name=""):
    name = name.upper()
    for w in HARAM_KEYWORDS:
        if w in name:
            return False
    return True

# --- 2. ارسال واتساب ---
def send_whatsapp(text):
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print("ناقص مفاتيح واتساب")
        return
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": MY_NUMBER, "type": "text", "text": {"body": text}}
    r = requests.post(url, headers=headers, json=data, timeout=10)
    print(f"واتساب: {r.status_code} {r.text[:200]}")

# --- 3. اخبار Finnhub ---
def get_news(symbol):
    try:
        today = datetime.now().date()
        yesterday = today - timedelta(days=1)
        url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={yesterday}&to={today}&token={FINNHUB_KEY}"
        news = requests.get(url, timeout=8).json()
        if not news:
            return "📰 سبب الصعود: بدون خبر ⚠️\n- صعود مضاربة بحت - انتبه، ادخل بنصف الكمية"
        latest = news[0]
        headline = latest.get("headline","")[:120]
        return f"📰 سبب الصعود: خبر ✅\n- {headline}"
    except:
        return "📰 الأخبار: تعذر الجلب"

# --- 4. اسعار Alpaca ---
def get_snapshot(symbol):
    try:
        url = f"https://data.alpaca.markets/v2/stocks/{symbol}/snapshot"
        headers = {"APCA-API-KEY-ID": ALPACA_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET}
        d = requests.get(url, headers=headers, timeout=8).json()
        bar = d.get("dailyBar", {})
        prev = d.get("prevDailyBar", {})
        minute = d.get("minuteBar", {})
        return {
            "price": minute.get("c", bar.get("c", 0)),
            "open": bar.get("o", 0),
            "high": bar.get("h", 0),
            "low": bar.get("l", 0),
            "prev_close": prev.get("c", 0),
            "volume": bar.get("v", 0),
        }
    except Exception as e:
        print(f"خطأ {symbol}: {e}")
        return None

# ذاكرة منع التكرار - 15 دقيقة
last_alert = {}

def can_alert(symbol, typ):
    key = f"{symbol}_{typ}"
    last = last_alert.get(key)
    if not last: return True
    return (datetime.now() - last).total_seconds() > 15*60

def mark_alert(symbol, typ):
    last_alert[f"{symbol}_{typ}"] = datetime.now()

def check_symbol(symbol):
    s = get_snapshot(symbol)
    if not s or s["price"] == 0: return
    price = s["price"]
    change = ((price - s["open"]) / s["open"] * 100) if s["open"] else 0

    # VWAP تقريبي = (high+low+close)/3
    vwap = (s["high"] + s["low"] + price) / 3

    news_text = ""
    # --- تنبيه 1: زخم قوي +2% ---
    if change >= 2 and can_alert(symbol, "momentum"):
        news_text = get_news(symbol)
        msg = f"""🔥🔥 زخم قوي | {symbol}
━━━━━━━━━━━━━━━
💰 الدخول: ${price:.4f}
⚡ من الافتتاح: +{change:.1f}%

{news_text}

🎯 هدف 1: ${price*1.05:.4f} (+5%)
🎯 هدف 2: ${price*1.10:.4f} (+10%)
🛑 وقف: ${price*0.98:.4f} (-2%)
⏰ {datetime.now().strftime('%H:%M:%S')}"""
        send_whatsapp(msg)
        mark_alert(symbol, "momentum")

    # --- تنبيه 2: اختراق مقاومة = اعلى سعر اليوم ---
    if price >= s["high"] * 1.005 and change > 0 and can_alert(symbol, "breakout"):
        msg = f"""🚀 اختراق مقاومة | {symbol}
💰 السعر: ${price:.4f}
📈 اخترق: ${s['high']:.4f}
⏰ {datetime.now().strftime('%H:%M:%S')}"""
        send_whatsapp(msg)
        mark_alert(symbol, "breakout")

    # --- تنبيه 3: صعود فوق VWAP ---
    if price > vwap and change > 0 and can_alert(symbol, "vwap"):
        msg = f"""🟢 صعود فوق VWAP | {symbol}
💰 السعر: ${price:.4f}
📊 VWAP: ${vwap:.4f}
📌 المشترين استلموا السيطرة
⏰ {datetime.now().strftime('%H:%M:%S')}"""
        send_whatsapp(msg)
        mark_alert(symbol, "vwap")

def is_market_open():
    # السوق الامريكي: الاثنين-الجمعة 5:30 مساءً - 12:00 منتصف الليل بتوقيت السعودية
    now = datetime.now(timezone(timedelta(hours=3)))
    if now.weekday() >= 5: return False
    t = now.hour * 60 + now.minute
    return 17*60+30 <= t <= 23*60+59

def main_loop():
    print("البوت شغال...")
    send_whatsapp("✅ البوت اشتغل على Render - بيتابع السوق الأمريكي")
    while True:
        try:
            if is_market_open():
                print(f"فحص... {datetime.now()}")
                for sym in HALAL_WATCHLIST:
                    if is_halal(sym):
                        check_symbol(sym)
                    time.sleep(1)
                time.sleep(300) # 5 دقايق
            else:
                print("السوق مقفل - انتظار...")
                time.sleep(300)
        except Exception as e:
            print(f"خطأ في اللوب: {e}")
            time.sleep(60)

@app.route("/")
def home():
    return "البوت شغال ✅"

@app.route("/test")
def test():
    send_whatsapp("🧪 رسالة تجريبية - البوت مربوط صح ✅")
    return "تم الارسال"

# تشغيل اللوب في الخلفية
threading.Thread(target=main_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
