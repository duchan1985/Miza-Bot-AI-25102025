import os, time, logging, requests, feedparser, schedule, pytz, threading
from datetime import datetime, timedelta
from dotenv import load_dotenv

# ======================
# CONFIG
# ======================
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_IDS = [i.strip() for i in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if i.strip()]
VN_TZ = pytz.timezone("Asia/Ho_Chi_Minh")

DATA_DIR = "data"
SENT_FILE = os.path.join(DATA_DIR, "sent_links.txt")
LOG_FILE = "miza_news_no_stock.log"
os.makedirs(DATA_DIR, exist_ok=True)
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s - %(message)s")

# ======================
# TELEGRAM
# ======================
def send_telegram(msg):
    """Gửi tin nhắn Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for chat_id in CHAT_IDS:
        try:
            requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"})
            logging.info(f"✅ Sent to {chat_id}")
        except Exception as e:
            logging.error(f"❌ Telegram error: {e}")

# ======================
# STORAGE
# ======================
def load_sent():
    return set(open(SENT_FILE, encoding="utf-8").read().splitlines()) if os.path.exists(SENT_FILE) else set()

def save_sent(link):
    with open(SENT_FILE, "a", encoding="utf-8") as f:
        f.write(link + "\n")

# ======================
# FETCH GOOGLE NEWS & YOUTUBE RSS
# ======================
def fetch_feeds(days=7):
    """Lấy dữ liệu RSS từ Google News & YouTube"""
    now = datetime.now(VN_TZ)
    cutoff = now - timedelta(days=days)
    feeds = [
        "https://news.google.com/rss/search?q=Miza|MZG|Giấy+Miza|Công+ty+Cổ+phần+Miza&hl=vi&gl=VN&ceid=VN:vi",
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCd2aU53aTTxxLONczZc34BA"
    ]

    results = []
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries:
                link = e.get("link", "")
                pub = e.get("published_parsed")
                if not pub:
                    continue
                pub_dt = datetime(*pub[:6], tzinfo=pytz.utc).astimezone(VN_TZ)
                if pub_dt < cutoff:
                    continue
                title = e.get("title", "Không có tiêu đề")
                source = e.get("source", {}).get("title", "")
                results.append({
                    "title": title,
                    "link": link,
                    "date": pub_dt,
                    "source": source
                })
        except Exception as e:
            logging.error(f"RSS parse error for {url}: {e}")

    results.sort(key=lambda x: x["date"], reverse=True)
    return results

# ======================
# SHORTEN URL
# ======================
def shorten_url(url):
    try:
        res = requests.get(f"https://is.gd/create.php?format=simple&url={url}", timeout=5)
        return res.text if res.status_code == 200 else url
    except:
        return url

# ======================
# FORMAT MESSAGE
# ======================
def format_message(news_list):
    lines = []
    for i, n in enumerate(news_list, 1):
        short = shorten_url(n["link"])
        src = f" - {n['source']}" if n["source"] else ""
        date_str = n["date"].strftime("%H:%M %d/%m/%Y")
        lines.append(f"{i}. <b>{n['title']}</b>{src}\n🗓️ {date_str}\n🔗 {short}")
    return "\n\n".join(lines)

# ======================
# DAILY SUMMARY JOB (9h sáng)
# ======================
def job_daily_summary():
    news = fetch_feeds(days=7)
    now = datetime.now(VN_TZ)

    header = f"📢 <b>Tổng hợp tin Miza (7 ngày gần nhất) - {now.strftime('%H:%M %d/%m')}</b>\n\n"
    if not news:
        send_telegram(header + "⚠️ Không có tin mới về Miza.")
        return

    body = format_message(news[:15])
    send_telegram(header + body)
    logging.info("✅ Sent daily summary.")

# ======================
# REALTIME CHECK (48h + gửi trễ 20 phút)
# ======================
def schedule_delayed_send(item):
    """Gửi tin mới sau 20 phút"""
    time.sleep(1200)
    msg = f"🆕 <b>Tin mới đăng từ Miza:</b>\n\n<b>{item['title']}</b>\n🗓️ {item['date'].strftime('%H:%M %d/%m/%Y')}\n🔗 {shorten_url(item['link'])}"
    send_telegram(msg)
    logging.info(f"🚀 Gửi tin mới sau 20 phút: {item['title']}")

def job_realtime_check():
    sent = load_sent()
    new_items = []
    feeds = fetch_feeds(days=2)
    for item in feeds:
        if item["link"] not in sent:
            hours_diff = (datetime.now(VN_TZ) - item["date"]).total_seconds() / 3600
            if hours_diff <= 48:
                new_items.append(item)
                save_sent(item["link"])
                threading.Thread(target=schedule_delayed_send, args=(item,)).start()

    if new_items:
        now = datetime.now(VN_TZ)
        logging.info(f"🚨 Phát hiện {len(new_items)} tin mới lúc {now.strftime('%H:%M %d/%m')}")
    else:
        print("⏳ Không có tin mới (check 20 phút).")

# ======================
# MAIN LOOP
# ======================
def main():
    logging.info("🚀 Miza News Bot started.")
    send_telegram("🚀 Miza News Bot tổng hợp tin tức & gửi tin mới trong 48h (delay 20 phút).")

    # Tổng hợp tin 9h sáng
    schedule.every().day.at("09:00").do(job_daily_summary)

    # Kiểm tra tin mới mỗi 20 phút
    schedule.every(20).minutes.do(job_realtime_check)

    job_realtime_check()
    job_daily_summary()

    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
