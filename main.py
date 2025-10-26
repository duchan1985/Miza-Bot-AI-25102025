import os, time, logging, requests, feedparser, schedule, pytz
from datetime import datetime, timedelta
from dotenv import load_dotenv

# ======================
# CONFIG
# ======================
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_IDS = [i.strip() for i in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if i.strip()]
VN_TZ = pytz.timezone("Asia/Ho_Chi_Minh")
RAPID_KEY = os.getenv("RAPID_API_KEY")

DATA_DIR = "data"
SENT_FILE = os.path.join(DATA_DIR, "sent_links.txt")
LOG_FILE = "miza_news_vn.log"
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
# GOOGLE NEWS 🇻🇳
# ======================
def get_google_news(days=20):
    """Lấy tin Google News (nguồn Việt Nam, ngôn ngữ tiếng Việt)"""
    feeds = [
        "https://news.google.com/rss/search?q=Miza|MZG|Miza+Group|Mizagroup|Giấy+Miza|Công+ty+Cổ+phần+Miza|Miza+Nghi+Sơn&hl=vi&gl=VN&ceid=VN:vi"
    ]
    now = datetime.now(VN_TZ)
    cutoff = now - timedelta(days=days)
    sent, results = load_sent(), []

    for url in feeds:
        feed = feedparser.parse(url)
        for e in feed.entries:
            link = e.get("link", "")
            pub = e.get("published_parsed")
            if not link or link in sent:
                continue
            pub_dt = datetime(*pub[:6], tzinfo=pytz.utc).astimezone(VN_TZ) if pub else now
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
            save_sent(link)
    results.sort(key=lambda x: x["date"], reverse=True)
    return results[:10]

# ======================
# YOUTUBE 🇻🇳 (RapidAPI)
# ======================
def get_youtube_videos(query="Miza Việt Nam"):
    """Lấy video YouTube có ngôn ngữ và khu vực VN"""
    url = f"https://youtube138.p.rapidapi.com/search/?q={query}&hl=vi&gl=VN"
    headers = {"x-rapidapi-host": "youtube138.p.rapidapi.com", "x-rapidapi-key": RAPID_KEY}
    results = []
    try:
        res = requests.get(url, headers=headers, timeout=10)
        data = res.json()
        for item in data.get("contents", []):
            video = item.get("video")
            if video:
                title = video.get("title", "")
                vid = video.get("videoId")
                # Lọc video không phải tiếng Việt
                if any(x in title.lower() for x in ["official", "mv", "music", "remix", "lyrics", "song"]):
                    continue
                results.append(f"🎥 <b>{title}</b>\n🔗 https://www.youtube.com/watch?v={vid}")
    except Exception as e:
        logging.error(f"YouTube API error: {e}")
    return results[:5]

# ======================
# RÚT GỌN LINK
# ======================
def shorten_url(url):
    try:
        r = requests.get(f"https://tinyurl.com/api-create.php?url={url}", timeout=5)
        return r.text if r.status_code == 200 else url
    except:
        return url

# ======================
# FORMAT HIỂN THỊ
# ======================
def format_message(title, items):
    if not items:
        return ""
    lines = []
    for i, item in enumerate(items, 1):
        if isinstance(item, dict):
            short = shorten_url(item["link"])
            src = f" - {item['source']}" if item.get("source") else ""
            lines.append(f"{i}. <b>{item['title']}</b>{src}\n🔗 {short}")
        else:
            lines.append(f"{i}. {item}")
    return f"<b>{title}</b>\n\n" + "\n\n".join(lines)

# ======================
# JOB CHÍNH
# ======================
def job_20days():
    send_telegram("🤖 Miza Bot đang tổng hợp tin tức Việt Nam (20 ngày gần nhất)...")

    news = get_google_news()
    yt = get_youtube_videos("Miza Việt Nam OR Giấy Miza OR MZG OR Miza Group")

    sections = [
        ("📰 Tin tức báo chí", news),
        ("🎥 Video YouTube", yt)
    ]

    now = datetime.now(VN_TZ)
    header = f"🆕 <b>Tin Miza mới phát sinh ({now.strftime('%H:%M %d/%m')})</b>\n\n"

    body = "\n\n\n".join(format_message(title, items) for title, items in sections if items)
    if body:
        send_telegram(header + body)
        print(header + body)
        logging.info("✅ Sent update to Telegram.")
    else:
        print("⏳ Không có tin mới (check).")

# ======================
# MAIN LOOP
# ======================
def main():
    logging.info("🚀 Miza News Bot VN started.")
    send_telegram("🚀 Miza News Bot VN khởi động thành công.")
    job_20days()
    # Tổng hợp mỗi ngày lúc 9h sáng
    schedule.every().day.at("09:00").do(job_20days)
    # Kiểm tra tin mới mỗi 5 phút
    schedule.every(5).minutes.do(job_20days)
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
