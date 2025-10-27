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
LOG_FILE = "miza_news_vn_v10.log"
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
            if pub_dt < cutoff:
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
# PARSE NGÀY 🇻🇳 (YouTube & Bài viết)
# ======================
def parse_vn_date(date_str):
    """
    Chuẩn hóa và phân tích ngày tiếng Việt từ YouTube hoặc bài báo.
    Hỗ trợ các dạng:
    - 'Đã công chiếu vào 14 thg 10, 2025'
    - 'Công chiếu vào 30 thg 9'
    - '14 thg 10, 2025'
    - '14 thg 10'
    """
    try:
        if not date_str:
            return None

        s = date_str.lower().strip()
        s = re.sub(r"(đã|công chiếu|đăng|vào|on|ra mắt|phát hành)", "", s).strip()

        # Có năm
        match_year = re.search(r"(\d{1,2})\s*thg\s*(\d{1,2}),?\s*(\d{4})", s)
        if match_year:
            d, m, y = int(match_year.group(1)), int(match_year.group(2)), int(match_year.group(3))
            return datetime(y, m, d, tzinfo=VN_TZ)

        # Không có năm -> mặc định năm hiện tại
        match_no_year = re.search(r"(\d{1,2})\s*thg\s*(\d{1,2})", s)
        if match_no_year:
            d, m = int(match_no_year.group(1)), int(match_no_year.group(2))
            current_year = datetime.now(VN_TZ).year
            return datetime(current_year, m, d, tzinfo=VN_TZ)

    except Exception as e:
        logging.error(f"Parse VN date error: {e}")
    return None

# ======================
# YOUTUBE 🇻🇳
# ======================
def get_youtube_videos(query="MIZA CORP"):
    """Lấy video từ kênh MIZA chính thức, đúng ngày công chiếu thật"""
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
            if any(x in title.lower() for x in ["myra", "remix", "show", "mv", "trần", "music"]):
                continue
            vid = video.get("videoId")
            pub_text = video.get("publishedTimeText", "")
            date_pub = parse_vn_date(pub_text)
            if not date_pub:
                continue
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
# ======================
def get_mzg_price():
    """Lấy giá MZG gần nhất từ CafeF hoặc 24hMoney, kèm thời gian cập nhật thực tế"""
    try:
        url = "https://cafef.vn/du-lieu/upcom/mzg-cong-ty-co-phan-miza.chn"
        res = requests.get(url, timeout=10)
        res.encoding = "utf-8"

        # Giá, thay đổi, thời gian cập nhật
        match_price = re.search(r"Giá hiện tại.*?(\d{1,3}(?:\.\d{3})*)", res.text)
        match_change = re.search(r"([-+]?\d+\.\d+|\+\d+|\-\d+|\d+)%", res.text)
        match_time = re.search(r"Cập nhật lúc\s*(\d{2}:\d{2}:\d{2}\s*\d{2}/\d{2})", res.text)

        if match_price:
            price = float(match_price.group(1).replace(".", ""))
            change = match_change.group(1) if match_change else "0%"
            updated_time = match_time.group(1) if match_time else datetime.now(VN_TZ).strftime("%H:%M %d/%m")
            return price, change, updated_time

    except Exception as e:
        logging.error(f"CafeF fetch error: {e}")

    # fallback sang 24hMoney
    try:
        url = "https://24hmoney.vn/ma-chung-khoan/MZG"
        res = requests.get(url, timeout=10)
        res.encoding = "utf-8"
        match = re.search(r"(\d{1,3}(?:\.\d{3})*)(?:<\/div>\s*<div[^>]*>0\.00|\s*<\/span>)", res.text)
        if match:
            price = float(match.group(1).replace(".", ""))
            updated_time = datetime.now(VN_TZ).strftime("%H:%M %d/%m")
            return price, "N/A", updated_time
    except Exception as e:
        logging.error(f"24hMoney fetch error: {e}")

    return None, None, None

# ======================
# SHORTEN URL
# ======================
def shorten_url(url):
    try:
        r = requests.get(f"https://is.gd/create.php?format=simple&url={url}", timeout=5)
        return r.text if r.status_code == 200 else url
    except:
        return url

# ======================
# FORMAT
# ======================
def format_news(title, items):
    if not items:
        return ""
    lines = []
    for i, item in enumerate(items, 1):
        short = shorten_url(item["link"])
        src = f" - {item.get('source', '')}" if item.get("source") else ""
        date_str = item["date"].strftime("%d/%m/%Y")
        lines.append(f"{i}. <b>{item['title']}</b>{src}\n🗓️ Ngày phát hành: {date_str}\n🔗 {short}")
    return f"<b>{title}</b>\n\n" + "\n\n".join(lines)

# ======================
# JOBS
# ======================
def job_daily_summary():
    now = datetime.now(VN_TZ)
    start_date = (now - timedelta(days=8)).strftime("%d/%m")
    end_date = (now - timedelta(days=1)).strftime("%d/%m/%Y")

    news = get_google_news(days=7)
    yt = get_youtube_videos("MIZA CORP")

    price, change, updated_time = get_mzg_price()
    price_line = f"📈 Giá cổ phiếu <b>MZG</b>: <b>{price:.2f} VNĐ</b> ({change})\n🕓 Cập nhật: {updated_time}\n\n" if price else "📉 Giá MZG: <i>chưa cập nhật</i>\n\n"

    header = f"📢 <b>Tổng hợp tin Miza ({start_date} → {end_date})</b>\n\n"
    body = format_news("📰 Tin tức báo chí", news[:10]) + "\n\n" + format_news("🎥 Video YouTube", yt[:5])
    send_telegram(price_line + header + body)
    logging.info("✅ Sent daily summary.")

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

def job_stock_update():
    price, change, updated_time = get_mzg_price()
    now = datetime.now(VN_TZ)
    if price:
        msg = f"📈 Giá cổ phiếu MZG: <b>{price:.2f} VNĐ</b> ({change})\n🕓 Cập nhật: {updated_time}"
    else:
        msg = f"📉 Không lấy được giá MZG lúc {now.strftime('%H:%M %d/%m')}"
    send_telegram(msg)
    logging.info("📊 Sent stock update.")

# ======================
# MAIN
# ======================
def main():
    logging.info("🚀 Miza News Bot VN started (v10).")
    send_telegram("🚀 Miza Bot VN (v10) – Ngày phát hành thực & giá MZG mới nhất với thời gian cập nhật thực tế.")

    schedule.every().day.at("09:00").do(job_daily_summary)
    schedule.every(20).minutes.do(job_realtime)
    schedule.every().day.at("09:00").do(job_stock_update)
    schedule.every().day.at("12:00").do(job_stock_update)
    schedule.every().day.at("15:00").do(job_stock_update)

    job_realtime()
    job_stock_update()

    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
