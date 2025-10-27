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
LOG_FILE = "miza_news_vn_v6_price_latest.log"
os.makedirs(DATA_DIR, exist_ok=True)
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s - %(message)s")

# ======================
# TELEGRAM
# ======================
def send_telegram(msg):
    """Gửi tin nhắn Telegram tới tất cả chat id"""
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
def get_google_news(days=7):
    feeds = [
        "https://news.google.com/rss/search?q=Miza|MZG|Giấy+Miza|Công+ty+Cổ+phần+Miza|Nhà+máy+Miza+Nghi+Sơn&hl=vi&gl=VN&ceid=VN:vi"
    ]
    now = datetime.now(VN_TZ)
    cutoff = now - timedelta(days=days)
    results = []
    for url in feeds:
        feed = feedparser.parse(url)
        for e in feed.entries:
            link = e.get("link", "")
            pub = e.get("published_parsed") or e.get("updated_parsed")
            if not pub:
                continue
            pub_dt = datetime(*pub[:6], tzinfo=pytz.utc).astimezone(VN_TZ)
            if pub_dt.year != now.year or pub_dt < cutoff:
                continue
            title = e.get("title", "Không có tiêu đề")
            if not any(k.lower() in title.lower() for k in ["miza", "mzg", "giấy", "nghi sơn"]):
                continue
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
def parse_vn_date(date_str):
    """Chuyển chuỗi ngày YouTube (ví dụ '18 thg 10, 2025') thành datetime"""
    try:
        m = re.search(r"(\d+)\s*thg\s*(\d+),\s*(\d{4})", date_str)
        if m:
            day = int(m.group(1))
            month = int(m.group(2))
            year = int(m.group(3))
            return datetime(year, month, day, tzinfo=VN_TZ)
    except Exception as e:
        logging.error(f"Parse YouTube date error: {e}")
    return datetime.now(VN_TZ)

def get_youtube_videos(query="MIZA CORP"):
    url = f"https://youtube138.p.rapidapi.com/search/?q={query}&hl=vi&gl=VN"
    headers = {"x-rapidapi-host": "youtube138.p.rapidapi.com", "x-rapidapi-key": RAPID_KEY}
    results = []
    try:
        res = requests.get(url, headers=headers, timeout=10)
        data = res.json()
        for item in data.get("contents", []):
            video = item.get("video")
            if not video:
                continue
            title = video.get("title", "")
            author = video.get("author", {}).get("title", "")
            if not any(k in (author + title).lower() for k in ["miza", "mzg"]):
                continue
            if any(x in title.lower() for x in ["myra", "remix", "show", "ca khúc", "mv", "live", "trần", "music"]):
                continue
            vid = video.get("videoId")
            published = video.get("publishedTimeText", "")
            date_pub = parse_vn_date(published)
            results.append({
                "title": title,
                "link": f"https://www.youtube.com/watch?v={vid}",
                "date": date_pub,
                "source": author or "YouTube"
            })
    except Exception as e:
        logging.error(f"YouTube API error: {e}")
    results.sort(key=lambda x: x["date"], reverse=True)
    return results

# ======================
# GIÁ CỔ PHIẾU MZG 📈
def get_mzg_price():
    """Lấy giá cổ phiếu MZG gần nhất từ nguồn Việt Nam"""
    try:
        url = "https://cafef.vn/du-lieu/upcom/mzg-cong-ty-co-phan-miza.chn"
        res = requests.get(url, timeout=10)
        res.encoding = "utf-8"
        # Tìm đoạn giá trong trang
        m = re.search(r"Giá cổ phiếu.*?(\d{1,3}(?:\.\d{3})*(?:,\d+)?)\s*VNĐ", res.text)
        if m:
            # xử lý dấu '.' và ',' nếu có
            val = m.group(1).replace(".", "").replace(",", ".")
            price = float(val)
            return price
    except Exception as e:
        logging.error(f"MZG price fetch error: {e}")
    return None

# ======================
# SHORTEN URL
def shorten_url(url):
    try:
        r = requests.get(f"https://is.gd/create.php?format=simple&url={url}", timeout=5)
        return r.text if r.status_code == 200 else url
    except:
        return url

# ======================
# FORMAT
def format_news(title, items):
    if not items:
        return ""
    lines = []
    for i, item in enumerate(items, 1):
        short = shorten_url(item["link"])
        src = f" - {item.get('source', '')}" if item.get("source") else ""
        date_str = item["date"].strftime("%d/%m/%Y")
        lines.append(f"{i}. <b>{item['title']}</b>{src}\n🗓️ {date_str}\n🔗 {short}")
    return f"<b>{title}</b>\n\n" + "\n\n".join(lines)

# ======================
# TỔNG HỢP 9H SÁNG
def job_daily_summary():
    now = datetime.now(VN_TZ)
    start_date = (now - timedelta(days=8)).strftime("%d/%m")
    end_date = (now - timedelta(days=1)).strftime("%d/%m/%Y")

    news = get_google_news(days=7)
    yt = get_youtube_videos("MIZA CORP")

    price = get_mzg_price()
    if price is not None:
        price_line = f"📈 Giá cổ phiếu <b>MZG</b> gần nhất: <b>{price:.2f} VNĐ</b>\n\n"
    else:
        price_line = "📈 Giá cổ phiếu MZG: <i>chưa cập nhật</i>\n\n"

    header = f"📢 <b>Tổng hợp tin Miza ({start_date} → {end_date})</b>\n\n"
    body = format_news("📰 Tin tức báo chí", news[:10]) + "\n\n" + format_news("🎥 Video YouTube", yt[:5])
    send_telegram(price_line + header + body)
    logging.info("✅ Sent daily summary.")

# ======================
# REALTIME 48H
def job_realtime():
    sent = load_sent()
    new_items = []
    feeds = get_google_news(days=2) + get_youtube_videos("MIZA CORP")

    for item in feeds:
        if item["link"] not in sent:
            hours_diff = (datetime.now(VN_TZ) - item["date"]).total_seconds() / 3600
            if hours_diff <= 48:
                new_items.append(item)
                save_sent(item["link"])

    if new_items:
        now = datetime.now(VN_TZ)
        header = f"🆕 <b>Tin Miza mới (48h gần nhất) - {now.strftime('%H:%M %d/%m')}</b>\n\n"
        body = format_news("Bài mới phát sinh", new_items[:10])
        send_telegram(header + body)
        logging.info(f"🚨 Sent {len(new_items)} new items (48h).")
    else:
        print("⏳ Không có tin mới (check 20 phút).")

# ======================
# GIÁ CỔ PHIẾU MZG (3 KHUNG GIỜ: 9h, 12h, 15h)
def job_stock_update():
    now = datetime.now(VN_TZ)
    price = get_mzg_price()
    if price is not None:
        msg = f"📈 <b>Giá cổ phiếu MZG</b> lúc {now.strftime('%H:%M %d/%m')} là <b>{price:.2f} VNĐ</b>"
    else:
        msg = f"📉 Không lấy được giá MZG lúc {now.strftime('%H:%M %d/%m')}"
    send_telegram(msg)
    logging.info("📊 Sent stock update.")
    print(msg)

# ======================
# MAIN
def main():
    logging.info("🚀 Miza News Bot VN started (v6-price-latest).")
    send_telegram("🚀 Miza Bot VN khởi động (v6-price-latest) – giá cổ phiếu MZG đã lấy **giá gần nhất**.")

    schedule.every().day.at("09:00").do(job_daily_summary)
    schedule.every(20).minutes.do(job_realtime)
    schedule.every().day.at("09:00").do(job_stock_update)
    schedule.every().day.at("12:00").do(job_stock_update)
    schedule.every().day.at("15:00").do(job_stock_update)

    # Khởi chạy ngay khi bắt đầu
    job_realtime()
    job_stock_update()

    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
