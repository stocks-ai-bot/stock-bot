import os
import requests
import json
from datetime import datetime, timedelta
import yfinance as yf
from apscheduler.schedulers.blocking import BlockingScheduler
from flask import Flask
import threading

app = Flask(__name__)

# ============================================================
# CONFIGURATION — Set these in Render Environment Variables
# ============================================================
GROQ_API_KEY    = os.environ.get("GROQ_API_KEY")
SLACK_WEBHOOK   = os.environ.get("SLACK_WEBHOOK_DAILY_NEWS")

# ============================================================
# STOCK LIST
# ============================================================
STOCKS = [
    {"name": "Oswal Pumps",           "bse": "542942", "nse": "OSWALPUMP",   "yf": "OSWALPUMP.NS"},
    {"name": "Sterling & Wilson",      "bse": "543263", "nse": "STERLINGWIL", "yf": "STERLINGWIL.NS"},
    {"name": "Monarch Survey",         "bse": "543538", "nse": "MONARCHSUR",  "yf": "MONARCHSUR.NS"},
    {"name": "ITC Hotels",             "bse": "543929", "nse": "ITCHOTELS",   "yf": "ITCHOTELS.NS"},
    {"name": "Ahlada Engineers",       "bse": "541303", "nse": "AHLADA",      "yf": "AHLADA.NS"},
    {"name": "HDFC Bank",              "bse": "500180", "nse": "HDFCBANK",    "yf": "HDFCBANK.NS"},
    {"name": "Navkar Corporation",     "bse": "539332", "nse": "NAVKARCORP",  "yf": "NAVKARCORP.NS"},
    {"name": "Guj. Ambuja Exports",    "bse": "524226", "nse": "GUJAMBEXPO",  "yf": "GUJAMBEXPO.NS"},
    {"name": "Axtel Industries",       "bse": "543716", "nse": "AXTEL",       "yf": "AXTEL.NS"},
    {"name": "Godawari Power",         "bse": "532734", "nse": "GODAWARIPOW", "yf": "GODAWARIPOW.NS"},
    {"name": "Borosil Renewables",     "bse": "538979", "nse": "BORORENEW",   "yf": "BORORENEW.NS"},
    {"name": "Yes Bank",               "bse": "532648", "nse": "YESBANK",     "yf": "YESBANK.NS"},
    {"name": "ITC",                    "bse": "500875", "nse": "ITC",         "yf": "ITC.NS"},
    {"name": "Tata Realty (TARIL)",    "bse": "543091", "nse": "TARIL",  "yf": "TARIL.NS"},
    {"name": "Infosys",                "bse": "500209", "nse": "INFY",   "yf": "INFY.NS"}
]

# ============================================================
# FETCH BSE ANNOUNCEMENTS
# ============================================================
def fetch_bse_announcements(bse_code):
    try:
        today = datetime.now().strftime("%Y%m%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        url = (
            f"https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
            f"?pageno=1&strCat=-1&strPrevDate={yesterday}&strScrip={bse_code}"
            f"&strSearch=P&strToDate={today}&strType=C&subcategory=-1"
        )
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.bseindia.com/"
        }
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        announcements = []
        if "Table" in data:
            for item in data["Table"][:3]:  # top 3 announcements
                announcements.append({
                    "headline": item.get("HEADLINE", ""),
                    "details": item.get("ATTACHMENTNAME", ""),
                    "date": item.get("News_submission_dt", ""),
                    "source": "BSE"
                })
        return announcements
    except Exception as e:
        print(f"BSE fetch error for {bse_code}: {e}")
        return []

# ============================================================
# FETCH NSE ANNOUNCEMENTS
# ============================================================
def fetch_nse_announcements(nse_symbol):
    try:
        url = f"https://www.nseindia.com/api/corp-announcements?index=equities&symbol={nse_symbol}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/"
        }
        session = requests.Session()
        # Get cookies first
        session.get("https://www.nseindia.com", headers=headers, timeout=10)
        r = session.get(url, headers=headers, timeout=10)
        data = r.json()
        announcements = []
        if isinstance(data, list):
            for item in data[:3]:
                announcements.append({
                    "headline": item.get("subject", ""),
                    "details": item.get("desc", ""),
                    "date": item.get("bflag", ""),
                    "source": "NSE"
                })
        return announcements
    except Exception as e:
        print(f"NSE fetch error for {nse_symbol}: {e}")
        return []

# ============================================================
# FETCH STOCK PRICE via yfinance
# ============================================================
def fetch_stock_price(yf_symbol, stock_name):
    try:
        ticker = yf.Ticker(yf_symbol)
        hist = ticker.history(period="2d")
        if hist.empty:
            return None
        current = round(hist["Close"].iloc[-1], 2)
        prev    = round(hist["Close"].iloc[-2], 2) if len(hist) > 1 else current
        change  = round(current - prev, 2)
        pct     = round((change / prev) * 100, 2) if prev else 0
        return {
            "price": current,
            "change": change,
            "pct": pct
        }
    except Exception as e:
        print(f"Price fetch error for {stock_name}: {e}")
        return None

# ============================================================
# SUMMARIZE WITH GROQ
# ============================================================
def summarize_with_groq(stock_data_text):
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama-3.1-8b-instant",
            "max_tokens": 2000,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a stock market analyst for Indian markets. "
                        "Create a morning briefing for Slack.\n\n"
                        "STRICT SLACK FORMATTING:\n"
                        "- Use *text* for bold (single asterisk only)\n"
                        "- Use • for bullet points\n"
                        "- Never use ** double asterisk\n"
                        "- Never use ## headers\n\n"
                        "FORMAT:\n"
                        "🌅 *Good Morning! Stock Watchlist — {date}*\n"
                        "━━━━━━━━━━━━━━━━━━━━\n\n"
                        "For each stock with news or price movement:\n"
                        "*STOCK NAME* — ₹{price} ({change}%)\n"
                        "• *Announcement:* what happened\n"
                        "• *Impact:* brief one-line analysis\n\n"
                        "Skip stocks with zero news and no significant price move.\n\n"
                        "━━━━━━━━━━━━━━━━━━━━\n"
                        "⚡ *Market Sentiment:* one line\n\n"
                        "Be crisp, factual, no filler words."
                    )
                },
                {
                    "role": "user",
                    "content": f"Here is today's data for my 13 stock watchlist:\n\n{stock_data_text}\n\nCreate the morning briefing now."
                }
            ]
        }
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"Groq error: {e}")
        return "Error generating summary."

# ============================================================
# POST TO SLACK
# ============================================================
def post_to_slack(message):
    try:
        payload = {"text": message}
        r = requests.post(SLACK_WEBHOOK, json=payload, timeout=10)
        print(f"Slack response: {r.status_code}")
    except Exception as e:
        print(f"Slack post error: {e}")

# ============================================================
# MAIN JOB — RUNS AT 8 AM IST DAILY
# ============================================================
def run_daily_news_bot():
    print(f"[{datetime.now()}] Starting Bot 1 — Daily News...")
    
    all_stock_data = []

    for stock in STOCKS:
        print(f"  Fetching: {stock['name']}")
        
        # Fetch from BSE
        bse_news = fetch_bse_announcements(stock["bse"])
        
        # Fetch from NSE
        nse_news = fetch_nse_announcements(stock["nse"])
        
        # Fetch price
        price_info = fetch_stock_price(stock["yf"], stock["name"])
        
        # Combine
        all_announcements = bse_news + nse_news
        
        stock_summary = f"STOCK: {stock['name']}\n"
        
        if price_info:
            arrow = "📈" if price_info["pct"] >= 0 else "📉"
            stock_summary += f"Price: ₹{price_info['price']} {arrow} {price_info['pct']}%\n"
        
        if all_announcements:
            stock_summary += "Announcements:\n"
            for ann in all_announcements:
                stock_summary += f"  [{ann['source']}] {ann['headline']}\n"
        else:
            stock_summary += "Announcements: None today\n"
        
        all_stock_data.append(stock_summary)

    # Combine all data
    combined = "\n".join(all_stock_data)
    combined += f"\n\nDate: {datetime.now().strftime('%d %B %Y, %A')}"
    
    # Summarize with Groq
    print("  Summarizing with Groq...")
    summary = summarize_with_groq(combined)
    
    # Post to Slack
    print("  Posting to Slack...")
    post_to_slack(summary)
    
    print(f"[{datetime.now()}] Bot 1 completed!")

# ============================================================
# FLASK KEEP-ALIVE ENDPOINT
# ============================================================
@app.route("/")
def home():
    return "Stock Bot 1 is running! ✅"

@app.route("/run-now")
def run_now():
    """Manual trigger endpoint"""
    threading.Thread(target=run_daily_news_bot).start()
    return "Bot 1 triggered! Check Slack in ~30 seconds."

# ============================================================
# SCHEDULER — 8:00 AM IST = 2:30 AM UTC
# ============================================================
def start_scheduler():
    scheduler = BlockingScheduler(timezone="Asia/Kolkata")
    scheduler.add_job(
        run_daily_news_bot,
        "cron",
        hour=8,
        minute=0,
        day_of_week="mon-fri"
    )
    print("Scheduler started — Bot 1 runs at 8:00 AM IST on weekdays")
    scheduler.start()

# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    # Start scheduler in background thread
    scheduler_thread = threading.Thread(target=start_scheduler, daemon=True)
    scheduler_thread.start()
    
    # Start Flask (keeps Render service alive)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
