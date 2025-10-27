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

DATA_DIR = "data"
SENT_FILE = os.path.join(DATA_DIR, "sent_links.txt")
LOG_FILE = "miza_news_final.log"
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
# GIÁ CỔ PHIẾU MZG 📈 (CẬP NHẬT CHUẨN)
# ======================
def get_mzg_price():
    """
    Lấy giá MZG gần nhất từ CafeF hoặc 24hMoney.
    Nếu là Thứ 7/CN -> tự động lấy giá phiên Thứ 6 gần nhất.
    """
    today = datetime.now(VN_TZ)
    weekday = today.weekday()
    if weekday >= 5:  # Thứ 7 hoặc CN
        target_day = today - timedelta(days=weekday - 4)
    else:
        target_day = today

    # ---- ƯU TIÊN CAFE.F ----
    try:
        url = "https://s.cafef.vn/upcom/MZG-cong-ty-co-phan-miza.chn"
        res = requests.get(url, timeout=10)
        res.encoding = "utf-8"

        # Lấy giá hiện tại
        match_price = re.search(r'<div class="price-item[^>]*">([\d.,]+)</div>', res.text)
        # Lấy thay đổi %
        match_change = re.search(r'<div class="price-change[^>]*">([^<]+)</div>', res.text)
        # Lấy thời gian cập nhật (nếu có)
        match_time = re.search(r"Cập nhật lúc\s*([\d: ]+\d{2}/\d{2})", res.text)

        if match_price:
            # xử lý giá -> 15.20 hoặc 15,200
            val = match_price.group(1).replace(",", "").replace(".", "")
            if len(val) > 3:
                price = float(val)
            else:
                price = float(match_price.group(1).replace(",", "."))
            change = match_change.group(1).strip() if match_change else "0%"
            updated_time = match_time.group(1) if match_time else target_day.strftime("%H:%M %d/%m")
            return price, change, updated_time

    except Exception as e:
        logging.error(f"CafeF fetch error: {e}")

    # ---- FALLBACK 24hMONEY ----
    try:
        url = "https://24hmoney.vn/ma-chung-khoan/MZG"
        res = requests.get(url, timeout=10)
        res.encoding = "utf-8"
        match = re.search(r'"currentPrice":\s*([\d.]+)', res.text)
        match_change = re.search(r'"changePercent":\s*"([^"]+)"', res.text)
        if match:
            price = float(match.group(1).replace(".", ""))
            change = match_change.group(1) if match_change else "N/A"
            updated_time = target_day.strftime("%H:%M %d/%m")
            return price, change, updated_time
    except Exception as e:
        logging.error(f"24hMoney fetch error: {e}")

    return None, None, None

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
    price, change, updated_time = get_mzg_price()

    now = datetime.now(VN_TZ)
    header = f"📢 <b>Tổng hợp tin Miza (7 ngày gần nhất) - {now.strftime('%H:%M %d/%m')}</b>\n\n"
    if price:
        header += f"📈 Giá cổ phiếu MZG: <b>{price:.2f} VNĐ</b> ({change})\n🕓 Cập nhật: {updated_time}\n\n"
    else:
        header += "⚠️ Không lấy được giá MZG.\n\n"

    if not news:
        send_telegram(header + "⚠️ Không có tin mới về Miza.")
        return

    body = format_message(news[:15])
    send_telegram(header + body)
    logging.info("✅ Sent daily summary.")

# ======================
# REAL-TIME MONITORING (5 phút)
# ======================
def job_realtime_check():
    sent = load_sent()
    new_items = []
    for item in fetch_feeds(days=2):
        if item["link"] not in sent:
            new_items.append(item)
            save_sent(item["link"])

    if new_items:
        now = datetime.now(VN_TZ)
        header = f"🆕 <b>Tin Miza mới (48h gần nhất) - {now.strftime('%H:%M %d/%m')}</b>\n\n"
        body = format_message(new_items[:5])
        send_telegram(header + body)
        logging.info(f"🚨 Sent {len(new_items)} new items.")
    else:
        print("⏳ Không có tin mới (check 5 phút).")

# ======================
# GIÁ CỔ PHIẾU (9h, 12h, 15h)
# ======================
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
# MAIN LOOP
# ======================
def main():
    logging.info("🚀 Miza News Bot RSS started (FINAL).")
    send_telegram("🚀 Miza News Bot RSS (FINAL) – hiển thị ngày đăng thật & giá MZG thực tế.")

    schedule.every().day.at("09:00").do(job_daily_summary)
    schedule.every().day.at("09:00").do(job_stock_update)
    schedule.every().day.at("12:00").do(job_stock_update)
    schedule.every().day.at("15:00").do(job_stock_update)
    schedule.every(5).minutes.do(job_realtime_check)

    job_realtime_check()
    job_stock_update()

    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
