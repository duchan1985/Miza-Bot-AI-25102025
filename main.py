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
LOG_FILE = "miza_news.log"
os.makedirs(DATA_DIR, exist_ok=True)
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s - %(message)s")

# ======================
# TELEGRAM
# ======================
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for chat_id in CHAT_IDS:
        try:
            requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"})
            logging.info(f"✅ Sent to {chat_id}")
        except Exception as e:
            logging.error(f"❌ Telegram send error: {e}")

# ======================
# STORAGE
# ======================
def load_sent():
    return set(open(SENT_FILE, encoding="utf-8").read().splitlines()) if os.path.exists(SENT_FILE) else set()
def save_sent(link):
    with open(SENT_FILE, "a", encoding="utf-8") as f: f.write(link + "\n")

# ======================
# GOOGLE NEWS (RSS)
# ======================
def get_google_news(days=20):
    feeds = [
        "https://news.google.com/rss/search?q=Miza&hl=vi&gl=VN&ceid=VN:vi",
        "https://news.google.com/rss/search?q=MZG&hl=vi&gl=VN&ceid=VN:vi",
        "https://news.google.com/rss/search?q=Miza+Nghi+Sơn&hl=vi&gl=VN&ceid=VN:vi"
    ]
    now = datetime.now(VN_TZ)
    cutoff = now - timedelta(days=days)
    sent, results = load_sent(), []
    for url in feeds:
        feed = feedparser.parse(url)
        for e in feed.entries:
            link = e.get("link", "")
            pub = e.get("published_parsed")
            if not link or link in sent: continue
            pub_dt = datetime(*pub[:6], tzinfo=pytz.utc).astimezone(VN_TZ) if pub else now
            if pub_dt < cutoff: continue
            title = e.get("title", "Không có tiêu đề")
            results.append(f"📰 <b>{title}</b>\n🔗 {link}")
            save_sent(link)
    return results

# ======================
# YOUTUBE (RapidAPI)
# ======================
def get_youtube_videos(query="MIZACORP"):
    url = f"https://youtube138.p.rapidapi.com/search/?q={query}&hl=en&gl=VN"
    headers = {"x-rapidapi-host": "youtube138.p.rapidapi.com", "x-rapidapi-key": RAPID_KEY}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        data = res.json()
        results = []
        for item in data.get("contents", []):
            video = item.get("video")
            if video:
                title = video.get("title", "No title")
                vid = video.get("videoId")
                results.append(f"🎥 <b>{title}</b>\n🔗 https://www.youtube.com/watch?v={vid}")
        return results[:10]
    except Exception as e:
        logging.error(f"YouTube API error: {e}")
        return []

# ======================
# TIKTOK (RapidAPI)
# ======================
def get_tiktok_videos(secUid, days=20):
    url = f"https://tiktok-api23.p.rapidapi.com/api/user/posts?secUid={secUid}&count=20&cursor=0"
    headers = {"x-rapidapi-host": "tiktok-api23.p.rapidapi.com", "x-rapidapi-key": RAPID_KEY}
    cutoff = datetime.now(VN_TZ) - timedelta(days=days)
    results = []
    try:
        res = requests.get(url, headers=headers, timeout=10)
        data = res.json()
        for item in data.get("data", []):
            title = item.get("desc", "Video TikTok không tiêu đề")
            link = f"https://www.tiktok.com/@{item['author']['uniqueId']}/video/{item['id']}"
            create_time = datetime.fromtimestamp(item.get("createTime", 0), tz=VN_TZ)
            if create_time >= cutoff:
                results.append(f"🎵 <b>{title}</b>\n🔗 {link}")
    except Exception as e:
        logging.error(f"TikTok API error: {e}")
    return results[:10]

# ======================
# INSTAGRAM (RapidAPI)
# ======================
def get_instagram_posts(username="mizagroupvn"):
    url = "https://instagram120.p.rapidapi.com/api/instagram/posts"
    headers = {
        "content-type": "application/json",
        "x-rapidapi-host": "instagram120.p.rapidapi.com",
        "x-rapidapi-key": RAPID_KEY
    }
    payload = {"username": username, "maxId": ""}
    results = []
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        data = res.json()
        for item in data.get("data", []):
            caption = item.get("caption", "Không có mô tả")
            link = item.get("link", "")
            results.append(f"📸 <b>{caption}</b>\n🔗 {link}")
    except Exception as e:
        logging.error(f"Instagram API error: {e}")
    return results[:10]

# ======================
# FACEBOOK (RapidAPI)
# ======================
def get_facebook_posts(page_id="100063667778486"):
    url = f"https://facebook-scraper3.p.rapidapi.com/page/posts?page_id={page_id}"
    headers = {
        "x-rapidapi-host": "facebook-scraper3.p.rapidapi.com",
        "x-rapidapi-key": RAPID_KEY
    }
    results = []
    try:
        res = requests.get(url, headers=headers, timeout=10)
        data = res.json()
        for item in data.get("data", []):
            msg = item.get("text", "Bài viết Facebook không có nội dung")
            link = item.get("post_url", "")
            results.append(f"📘 <b>{msg}</b>\n🔗 {link}")
    except Exception as e:
        logging.error(f"Facebook API error: {e}")
    return results[:10]

# ======================
# MAIN JOB
# ======================
def job_20days():
    send_telegram("🤖 Miza News Bot đang tổng hợp tin tức từ đa nền tảng (20 ngày gần nhất)...")

    news = get_google_news()
    yt = get_youtube_videos("MIZACORP")
    tiktok_1 = get_tiktok_videos("MS4wLjABAAAAG7g23C7SJEh6wVYxB01W0n8z7o4gRT8LgKgrmMZwFltT8_XHXxqpvTiHeFShKlfA")
    tiktok_2 = get_tiktok_videos("MS4wLjABAAAA0B4wNw0FQXK3Q3wGzTq1Pzqj_ghvUhbjMwKqG8RKh1m7A9Q2vxL5eN7bA")
    insta = get_instagram_posts("mizagroupvn")
    fb = get_facebook_posts("100063667778486")

    sections = [
        ("📰 Tin tức báo chí", news),
        ("🎥 Video YouTube", yt),
        ("🎵 TikTok @_mizagroup", tiktok_1),
        ("🎵 TikTok @miza.group4", tiktok_2),
        ("📸 Instagram", insta),
        ("📘 Facebook Page", fb)
    ]

    for title, items in sections:
        if items:
            msg = f"<b>{title}</b>\n\n" + "\n\n".join(f"{i+1}. {v}" for i, v in enumerate(items))
            send_telegram(msg)
            time.sleep(2)

    logging.info("✅ Job 20days completed.")

# ======================
# MAIN LOOP
# ======================
def main():
    logging.info("🚀 Miza News Bot (Full API) started.")
    send_telegram("🚀 Miza News Bot (Full API) khởi động thành công.")
    job_20days()
    schedule.every().day.at("09:00").do(job_20days)
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
