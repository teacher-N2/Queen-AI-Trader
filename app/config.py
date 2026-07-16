import os
from dotenv import load_dotenv

load_dotenv()

TRADINGVIEW_WEBHOOK_SECRET = os.getenv("TRADINGVIEW_WEBHOOK_SECRET", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
MIN_QUEEN_SCORE = int(os.getenv("MIN_QUEEN_SCORE", "80"))
MAX_TRADES_PER_DAY = int(os.getenv("MAX_TRADES_PER_DAY", "7"))
MAX_DAILY_LOSSES = int(os.getenv("MAX_DAILY_LOSSES", "3"))
MAX_RISK_PERCENT_PER_TRADE = float(os.getenv("MAX_RISK_PERCENT_PER_TRADE", "0.5"))
