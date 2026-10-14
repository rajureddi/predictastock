"""
PredictaStock Pydantic Data Models & Schemas
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class RecommendationBase(BaseModel):
    id: str
    symbol: str
    name: str
    exchange: str = "NSE"
    sector: Optional[str] = "Other"
    rec_date: str
    reference_price: float
    reference_timestamp: str
    expected_target_price: float
    expected_range_low: float
    expected_range_high: float
    expected_appreciation_pct: float
    risk_level: str  # 'Low', 'Medium', 'High'
    status: str
    supporting_reasons: Optional[List[str]] = []
    downside_risks: Optional[List[str]] = []
    technical_summary: Optional[str] = None
    fundamental_summary: Optional[str] = None
    news_summary: Optional[str] = None
    sentiment_score: float = 0.0
    sentiment_label: str = "Neutral"
    atr_14: float = 0.0
    volatility_5d_pct: float = 0.0
    support_level: Optional[float] = None
    resistance_level: Optional[float] = None
    confidence_text: str = "Not enough history yet to measure accuracy"
    model_version: str = "v2.0-QuantHybrid"


class TransactionCreate(BaseModel):
    symbol: str
    exchange: str = "NSE"
    transaction_type: str = "BUY"  # 'BUY' or 'SELL'
    transaction_date: str
    price: float
    quantity: int
    brokerage: Optional[float] = None
    recommendation_id: Optional[str] = None
    notes: Optional[str] = None


class HoldingItem(BaseModel):
    symbol: str
    name: str
    sector: str
    quantity: int
    avg_purchase_price: float
    total_invested: float
    latest_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    total_statutory_costs: float
    net_pnl_after_costs: float
    realized_pnl: float = 0.0
    stcg_quantity: int = 0
    ltcg_quantity: int = 0
    current_status: str
    risk_level: str
    alerts: List[str] = []


class PortfolioSummary(BaseModel):
    total_invested: float
    current_market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    realized_pnl: float
    net_pnl_after_costs: float
    total_costs_incurred: float
    sector_breakdown: Dict[str, float]  # sector name -> percentage
    sector_alerts: List[str] = []
    holdings: List[HoldingItem]


class ForecastEvaluationItem(BaseModel):
    id: str
    recommendation_id: str
    symbol: str
    start_date: str
    end_date: str
    original_reference_price: float
    predicted_target_price: float
    predicted_appreciation_pct: float
    actual_end_price: Optional[float] = None
    actual_appreciation_pct: Optional[float] = None
    forecast_error_pct: Optional[float] = None
    direction_correct: Optional[bool] = None
    nifty50_return_pct: Optional[float] = None
    alpha_vs_nifty_pct: Optional[float] = None
    user_actual_buy_price: Optional[float] = None
    user_actual_return_pct: Optional[float] = None
    status: str  # 'PENDING' or 'COMPLETED'


class ScorecardSummary(BaseModel):
    total_completed_forecasts: int
    directional_accuracy_pct: float  # Target > 55%
    avg_forecast_error_pct: float
    avg_model_return_pct: float
    avg_nifty_return_pct: float
    avg_alpha_pct: float
    downside_surprise_count: int
    status_text: str


class UserRegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None


class UserLoginRequest(BaseModel):
    username: str
    password: str


class CorporateActionCreate(BaseModel):
    symbol: str
    action_type: str  # 'SPLIT', 'BONUS', 'DIVIDEND'
    ex_date: str      # YYYY-MM-DD
    ratio: Optional[str] = "1:1"
    adjustment_factor: Optional[float] = 1.0
    dividend_amount: Optional[float] = 0.0
    record_date: Optional[str] = None


class EmailDispatchRequest(BaseModel):
    report_date: Optional[str] = None
    recipient_email: Optional[str] = None

