import os, time, logging, requests, feedparser, schedule, pytz, re
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
    """Đọc danh sách link đã gửi"""
    return set(open(SENT_FILE, encoding="utf-8").read().splitlines()) if os.path.exists(SENT_FILE) else set()

def save_sent(link):
    """Lưu link đã gửi"""
    with open(SENT_FILE, "a", encoding="utf-8") as f:
        f.write(link + "\n")

# ======================
# GOOGLE NEWS 🇻🇳
# ======================
def get_google_news(days=7):
    """Lấy tin Google News (chỉ bài đăng trong 7 ngày và đúng năm hiện tại)"""
    feeds = [
        "https://news.google.com/rss/search?q=Miza|MZG|Miza+Group|Mizagroup|Giấy+Miza|Công+ty+Cổ+phần+Miza|Miza+Nghi+Sơn&hl=vi&gl=VN&ceid=VN:vi"
    ]
    now = datetime.now(VN_TZ)
    cutoff = now - timedelta(days=days)
    results = []

    for url in feeds:
        feed = feedparser.parse(url)
        for e in feed.entries:
            link = e.get("link", "")
            pub = e.get("published_parsed")
            if not pub:
                continue

            pub_dt = datetime(*pub[:6], tzinfo=pytz.utc).astimezone(VN_TZ)

            # ❌ Chặn tin khác năm hiện tại
            if pub_dt.year != now.year:
                continue

            # ❌ Chặn tin cũ hơn 7 ngày
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

    results.sort(key=lambda x: x["date"], reverse=True)
    return results

# ======================
# YOUTUBE 🇻🇳
# ======================
def get_youtube_videos(query="Miza Việt Nam"):
    """Lấy video YouTube (VN)"""
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
                if any(x in title.lower() for x in ["music", "mv", "remix", "lyrics", "song"]):
                    continue
                results.append({
                    "title": title,
                    "link": f"https://www.youtube.com/watch?v={vid}",
                    "date": datetime.now(VN_TZ),
                    "source": "YouTube"
                })
    except Exception as e:
        logging.error(f"YouTube API error: {e}")
    return results

# ======================
# GIÁ CỔ PHIẾU MZG 📈
# ======================
def get_mzg_price_previous():
    """Lấy giá cổ phiếu MZG đóng cửa phiên trước từ Vietstock"""
    try:
        url = "https://finance.vietstock.vn/MZG-ctcp-miza.htm"
        res = requests.get(url, timeout=10)
        res.encoding = "utf-8"
        match = re.search(r'Giá đóng cửa.*?(\d{1,3}(?:\.\d{3})*)', res.text)
        if match:
            price = match.group(1).replace(".", "")
            return int(price)
    except Exception as e:
        logging.error(f"MZG price fetch error: {e}")
    return None

# ======================
# SHORTEN URL
# ======================
def shorten_url(url):
    try:
        r = requests.get(f"https://tinyurl.com/api-create.php?url={url}", timeout=5)
        return r.text if r.status_code == 200 else url
    except:
        return url

# ======================
# FORMAT
# ======================
def format_news(title, items):
    """Hiển thị danh sách tin có ngày đăng"""
    if not items:
        return ""
    lines = []
    for i, item in enumerate(items, 1):
        short = shorten_url(item["link"])
        src = f" - {item['source']}" if item.get("source") else ""
        date_str = item["date"].strftime("%d/%m/%Y %H:%M")
        lines.append(f"{i}. <b>{item['title']}</b>{src}\n🕓 {date_str}\n🔗 {short}")
    return f"<b>{title}</b>\n\n" + "\n\n".join(lines)

# ======================
# TỔNG HỢP HÀNG NGÀY (9H)
# ======================
def job_daily_summary():
    now = datetime.now(VN_TZ)
    start_date = (now - timedelta(days=8)).strftime("%d/%m")
    end_date = (now - timedelta(days=1)).strftime("%d/%m/%Y")

    news = get_google_news(days=7)
    yt = get_youtube_videos("Miza Việt Nam")

    # Lấy giá cổ phiếu hôm trước
    mzg_price = get_mzg_price_previous()
    if mzg_price:
        price_line = f"📈 Giá cổ phiếu <b>MZG</b> đóng cửa phiên {end_date}: <b>{mzg_price:,} VND</b>\n\n"
    else:
        price_line = "📈 Giá cổ phiếu MZG: <i>chưa cập nhật được</i>\n\n"

    header = f"📢 <b>Tổng hợp tin Miza ({start_date} → {end_date})</b>\n\n"
    body = format_news("📰 Tin tức báo chí", news[:10]) + "\n\n" + format_news("🎥 Video YouTube", yt[:5])

    send_telegram(price_line + header + body)
    logging.info("✅ Sent daily summary.")
    print(f"✅ Gửi tổng hợp tin 9h sáng ({start_date} → {end_date}).")

# ======================
# GỬI TIN MỚI TRONG 48H
# ======================
def job_realtime():
    sent = load_sent()
    new_items = []
    feeds = get_google_news(days=2) + get_youtube_videos("Miza Việt Nam")

    for item in feeds:
        if item["link"] not in sent:
            hours_diff = (datetime.now(VN_TZ) - item["date"]).total_seconds() / 3600
            if hours_diff <= 48:  # chỉ gửi tin trong 48 giờ qua
                new_items.append(item)
                save_sent(item["link"])

    if new_items:
        now = datetime.now(VN_TZ)
        header = f"🆕 <b>Tin Miza mới (48h gần nhất) - {now.strftime('%H:%M %d/%m')}</b>\n\n"
        body = format_news("Bài mới phát sinh", new_items[:10])
        send_telegram(header + body)
        print(f"🚨 Gửi {len(new_items)} tin mới phát sinh (48h).")
        logging.info(f"🚨 Sent {len(new_items)} new items (48h).")
    else:
        print("⏳ Không có tin mới (check 20 phút).")

# ======================
# MAIN
# ======================
def main():
    logging.info("🚀 Miza News Bot (VN - 7 ngày + 48h + Giá cổ phiếu + Lọc năm hiện tại) started.")
    send_telegram("🚀 Miza Bot VN khởi động (7 ngày + 48h + Giá cổ phiếu + Lọc năm hiện tại).")

    # Gửi tổng hợp lúc 9h sáng
    schedule.every().day.at("09:00").do(job_daily_summary)

    # Kiểm tra tin mới mỗi 20 phút
    schedule.every(20).minutes.do(job_realtime)

    # Chạy ngay khi khởi động
    job_realtime()

    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
