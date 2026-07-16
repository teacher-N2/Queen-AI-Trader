from typing import Literal, Optional
from pydantic import BaseModel, Field

class TradingSignal(BaseModel):
    secret: str
    symbol: str = "XAUUSD"
    timeframe: str
    side: Literal["BUY", "SELL"]
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: Optional[float] = None
    take_profit_3: Optional[float] = None

    liquidity_sweep: bool = False
    mss: bool = False
    fvg: bool = False
    order_block: bool = False
    session: Literal["ASIA", "LONDON", "NEW_YORK", "OTHER"] = "OTHER"
    rr: float = Field(ge=0)
    notes: str = ""

class ScoredSignal(BaseModel):
    signal: TradingSignal
    queen_score: int
    grade: str
    accepted: bool
    rejection_reason: str | None = None
