from datetime import date
from pathlib import Path
import json

from .config import MAX_TRADES_PER_DAY, MAX_DAILY_LOSSES

LOG_FILE = Path("trade_log.jsonl")

def _today_records():
    if not LOG_FILE.exists():
        return []
    today = date.today().isoformat()
    records = []
    for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
            if item.get("date") == today:
                records.append(item)
        except json.JSONDecodeError:
            continue
    return records

def can_send_new_trade():
    records = _today_records()
    trade_count = sum(1 for r in records if r.get("event") == "signal_sent")
    loss_count = sum(1 for r in records if r.get("event") == "trade_closed" and r.get("result") == "LOSS")

    if trade_count >= MAX_TRADES_PER_DAY:
        return False, "تم بلوغ الحد اليومي للصفقات"
    if loss_count >= MAX_DAILY_LOSSES:
        return False, "تم بلوغ حد الخسائر اليومي"
    return True, None

def append_log(payload: dict):
    payload = {"date": date.today().isoformat(), **payload}
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
