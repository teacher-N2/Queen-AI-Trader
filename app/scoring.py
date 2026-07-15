from .models import TradingSignal, ScoredSignal
from .config import MIN_QUEEN_SCORE

def calculate_score(signal: TradingSignal) -> ScoredSignal:
    score = 0

    # السيولة
    if signal.liquidity_sweep:
        score += 20

    # تغير هيكل السوق
    if signal.mss:
        score += 20

    # منطقة الدخول
    if signal.fvg:
        score += 12
    if signal.order_block:
        score += 8

    # التوقيت
    if signal.session in {"LONDON", "NEW_YORK"}:
        score += 15
    elif signal.session == "ASIA":
        score += 7

    # نسبة العائد إلى المخاطرة
    if signal.rr >= 4:
        score += 20
    elif signal.rr >= 3:
        score += 17
    elif signal.rr >= 2:
        score += 12
    elif signal.rr >= 1.5:
        score += 6

    # حد أقصى
    score = min(score, 100)

    if score >= 95:
        grade = "A+"
    elif score >= 90:
        grade = "A"
    elif score >= 85:
        grade = "B+"
    elif score >= 80:
        grade = "B"
    else:
        grade = "REJECT"

    accepted = score >= MIN_QUEEN_SCORE

    return ScoredSignal(
        signal=signal,
        queen_score=score,
        grade=grade,
        accepted=accepted,
        rejection_reason=None if accepted else f"Queen Score أقل من {MIN_QUEEN_SCORE}",
    )
