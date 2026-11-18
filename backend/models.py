"""Pydantic models for the trading app."""
from datetime import datetime, timezone
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict
import uuid


def _now():
    return datetime.now(timezone.utc)


class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    created_at: datetime


class DhanCredentialsInput(BaseModel):
    client_id: str
    access_token: str


class AliceCredentialsInput(BaseModel):
    user_id: str  # Alice Blue user id
    api_key: str


class IndMoneyCredentialsInput(BaseModel):
    access_token: str  # Bearer token from indstocks.com/app/api-trading


class DeltaCredentialsInput(BaseModel):
    api_key: str       # API Key from Delta Exchange dashboard
    api_secret: str    # API Secret from Delta Exchange dashboard
    environment: str = "india_prod"  # india_prod | global_prod | india_testnet | global_testnet


BROKER_CHOICES = ("dhan", "alice_blue", "indmoney", "delta_exchange")


class AlertConfigInput(BaseModel):
    alert_name: str
    enabled: bool = True
    transaction_type: str = "B"  # B or S
    quantity: int = 1
    exchange_segment: str = "nse_cm"
    product: str = "CNC"
    broker: str = "dhan"  # which broker to route to


class SymbolMappingInput(BaseModel):
    chartink_symbol: str  # the symbol name as Chartink sends it
    nse_symbol: str       # the NSE trading symbol (used for the order)
    quantity: Optional[int] = None     # fixed qty (takes precedence over amount)
    amount: Optional[float] = None     # rupee value → qty = floor(amount / trigger_price)
    broker: str = "*"     # "*" = any broker; specific broker overrides "*"
    transaction_type: Optional[str] = None  # B / S (overrides alert config if set)
    product: Optional[str] = None           # CNC / MIS / NRML (overrides if set)
    category: Optional[str] = None          # "large_cap" | "mid_cap" | "small_cap" for amount grouping


class SymbolMapping(SymbolMappingInput):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    created_at: datetime = Field(default_factory=_now)


CATEGORIES = ("large_cap", "mid_cap", "small_cap", "other")


class CategoryAmountInput(BaseModel):
    category: str  # large_cap | mid_cap | small_cap | other
    amount: float  # rupee value used to auto-calc qty = floor(amount / trigger_price)


class CategoryAmount(CategoryAmountInput):
    user_id: str
    created_at: datetime = Field(default_factory=_now)


class EmaScheduleInput(BaseModel):
    interval: str  # "1h" | "2h" | "daily"
    enabled: bool = True


class EmaSchedule(EmaScheduleInput):
    user_id: str
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_now)


class AlertConfig(AlertConfigInput):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    created_at: datetime = Field(default_factory=_now)


class Position(BaseModel):
    symbol: str
    exchange_segment: str
    quantity: int
    avg_price: float
    ltp: Optional[float] = None
    pnl: Optional[float] = None
    product: Optional[str] = None


class TradeLog(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    symbol: str
    quantity: int
    price: Optional[float] = None
    transaction_type: str
    order_type: str
    order_id: Optional[str] = None
    status: str
    message: Optional[str] = None
    source: str  # "chartink" | "ema_sl" | "manual"
    created_at: datetime = Field(default_factory=_now)


class WebhookLog(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    alert_name: Optional[str] = None
    scan_name: Optional[str] = None
    stocks: List[str] = []
    trigger_prices: List[float] = []
    raw_payload: dict
    processed: bool = False
    result_note: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)


class EmaSlRun(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    symbol: str
    quantity: int
    ema10: Optional[float] = None   # legacy rows only
    sl_trigger: Optional[float] = None
    atr: Optional[float] = None
    atr_stop: Optional[float] = None
    fixed_stop: Optional[float] = None
    basis: Optional[str] = None     # atr | fixed | previous
    order_id: Optional[str] = None
    status: str
    message: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)


class ManualOrderInput(BaseModel):
    """Used by the dashboard 'place order manually' form."""
    broker: str = "dhan"  # dhan | alice_blue | indmoney | delta_exchange
    symbol: str
    transaction_type: str = "B"  # B | S
    quantity: int = Field(..., gt=0)
    order_type: str = "MKT"  # MKT | L
    price: float = 0.0  # used when order_type=L
    product: str = "CNC"  # CNC | MIS | NRML
    exchange_segment: str = "nse_cm"  # nse_cm | bse_cm
    amo: bool = False  # After-Market Order flag
    auto_ema_sl: bool = False  # also place EMA10-based stoploss after entry
