"""
PredictaStock Stock Prediction Engine & Factor Methodology PDF Builder
Compiles an in-depth, technical and executive review document explaining:
- How the 5 stocks are chosen
- The 4 Quantitative Pillars and exact weights
- The Math (ATR-14) vs The AI (Groq 120B LLM committee)
- Real worked numerical example
- The News Veto Rule and 10-stage execution pipeline
"""
import os
import sys
from pathlib import Path
from datetime import datetime, date
from fpdf import FPDF

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
REPORTS_DIR = BASE_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)
ARTIFACT_DIR = Path("C:/Users/rajub/.gemini/antigravity-ide/brain/1f5f6481-599e-4132-9a3a-59fc646e07a9")


class FactorReportPDF(FPDF):
    def __init__(self):
        super().__init__(orientation='P', unit='mm', format='A4')
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(16, 18, 16)

    def header(self):
        if self.page_no() == 1:
            return # Cover has custom hero banner
        self.set_fill_color(11, 14, 20) # Obsidian header bar
        self.rect(0, 0, 210, 16, 'F')
        self.set_font('Helvetica', 'B', 8.5)
        self.set_text_color(255, 159, 28) # Bloomberg Amber
        self.set_xy(16, 3)
        self.cell(110, 5, 'PREDICTASTOCK AI  |  STOCK PREDICTION & FACTOR METHODOLOGY', align='L')
        self.set_font('Helvetica', '', 7.5)
        self.set_text_color(160, 175, 195)
        self.set_xy(126, 3)
        self.cell(68, 5, 'QUANTITATIVE & AI REVIEW GUIDE', align='R')
        self.set_draw_color(255, 159, 28)
        self.set_line_width(0.4)
        self.line(0, 16, 210, 16)
        self.ln(6)

    def footer(self):
        self.set_y(-14)
        self.set_draw_color(220, 226, 235)
        self.set_line_width(0.2)
        self.line(16, 283, 194, 283)
        self.set_font('Helvetica', 'I', 7.5)
        self.set_text_color(120, 130, 145)
        self.cell(100, 8, 'PredictaStock Research & Quantitative Methodology  *  Client Review', align='L')
        self.cell(78, 8, f'Page {self.page_no()}', align='R')

    def section_header(self, title, subtitle=None):
        self.ln(3)
        self.set_fill_color(244, 247, 252)
        self.set_draw_color(99, 102, 241) # Indigo accent
        self.set_line_width(0.6)
        self.rect(16, self.get_y(), 178, 9, 'DF')
        self.set_font('Helvetica', 'B', 10.5)
        self.set_text_color(15, 23, 42)
        self.set_xy(19, self.get_y() + 1.8)
        self.cell(172, 5, title)
        self.ln()
        if subtitle:
            self.set_font('Helvetica', 'I', 8)
            self.set_text_color(100, 116, 139)
            self.set_x(19)
            self.cell(172, 4, subtitle)
            self.ln()
        self.ln(2)

    def subsection_title(self, title):
        self.set_font('Helvetica', 'B', 9)
        self.set_text_color(79, 70, 229) # Indigo
        self.cell(0, 6, title)
        self.ln()

    def body_p(self, text):
        self.set_font('Helvetica', '', 8)
        self.set_text_color(30, 41, 59)
        self.multi_cell(178, 4.2, text)
        self.ln(1.5)

    def bullet(self, label, text):
        self.set_font('Helvetica', 'B', 8)
        self.set_text_color(15, 23, 42)
        self.cell(5, 4.2, 'o', align='C')
        self.cell(38, 4.2, f'{label}: ')
        self.set_font('Helvetica', '', 8)
        self.set_text_color(51, 65, 85)
        self.multi_cell(135, 4.2, text)
        self.ln(1)


def build_factors_pdf():
    pdf = FactorReportPDF()
    pdf.add_page()

    # =========================================================================
    # HERO COVER BANNER
    # =========================================================================
    pdf.set_fill_color(11, 14, 20)
    pdf.rect(0, 0, 210, 48, 'F')
    
    # Gold accent line
    pdf.set_fill_color(255, 159, 28)
    pdf.rect(0, 48, 210, 1.5, 'F')

    pdf.set_xy(16, 8)
    pdf.set_font('Helvetica', 'B', 17)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(178, 8, 'PREDICTASTOCK AI TERMINAL')
    pdf.ln()

    pdf.set_font('Helvetica', 'B', 10.5)
    pdf.set_text_color(255, 159, 28)
    pdf.cell(178, 6, 'HOW STOCKS ARE PREDICTED: FACTORS, MATHEMATICS & AI EXPLAINED')
    pdf.ln()

    pdf.set_font('Helvetica', '', 8)
    pdf.set_text_color(180, 195, 215)
    meta_line = f"Methodology Report  *  Target Markets: NSE / BSE  *  Date: {date.today().strftime('%d %B %Y')}  *  Inference: Groq (gpt-oss-120b)"
    pdf.cell(178, 5, meta_line)
    pdf.ln()

    pdf.set_y(54)

    # Core Question Answered
    pdf.section_header("1. EXECUTIVE SUMMARY: IS IT MATH, AI, OR BOTH?", "The Core Architectural Distinction Between Mathematical Boundaries and AI Reasoning")
    pdf.body_p(
        "A common misconception in retail trading software is that an AI Large Language Model (LLM) 'predicts' a future stock price. "
        "In institutional finance, allowing an LLM to guess future prices is dangerous because LLMs suffer from ungrounded hallucinations "
        "and cannot calculate physical volatility bounds."
    )
    pdf.body_p(
        "PredictaStock uses a HYBRID QUANTITATIVE-AI ARCHITECTURE with strict division of responsibility:\n"
        "1. The MATHEMATICS (100% Deterministic) calculates the exact price targets, upper resistance envelopes, and stop-loss boundaries using verified 14-period Average True Range (ATR-14) formulas.\n"
        "2. The QUANTITATIVE MULTI-FACTOR ENGINE screens and ranks all 60+ Nifty constituents across 4 weighted pillars to find the 5 highest-probability opportunities.\n"
        "3. The ARTIFICIAL INTELLIGENCE (Groq Cloud running openai/gpt-oss-120b) acts as an Adversarial Committee of 7 Specialist Analyst Desks to debate qualitative catalysts, identify tailwinds, challenge bull vs. bear theses, and calibrate the final trade execution plan."
    )

    # =========================================================================
    # SECTION 2: THE 4 PILLARS
    # =========================================================================
    pdf.section_header("2. THE 4 QUANTITATIVE PILLARS THAT DECIDE THE 5 STOCKS", "Mathematical Weighting Model Generating the Composite Score (0 to 100)")
    pdf.body_p(
        "Every single stock in the Nifty 50 and Nifty 100 universe is ingested and scored across 4 foundational pillars using the formula:\n"
        "Composite Score = (0.35 * Technical) + (0.25 * Fundamental) + (0.25 * News Sentiment) + (0.15 * Macro Flow)"
    )

    pillars = [
        ("Pillar 1: Technical Momentum", "35% Weight", "RSI-14 (sweet spot 45 to 68), price confirmed above 20-DMA trendline, positive MACD histogram expansion, dynamic support holding."),
        ("Pillar 2: Fundamental Durability", "25% Weight", "Tier-1 Nifty 50 core leadership (75 pts baseline), balance sheet solvency, conservative debt-to-equity, high Return on Capital Employed (ROCE)."),
        ("Pillar 3: News & Sentiment", "25% Weight", "Live rolling 7-day Google News RSS scraping with financial keyword tone analysis. Normalizes score [-1.0, 1.0] to [0, 100]. Subject to the News Veto Rule."),
        ("Pillar 4: Macro & Liquidity Flow", "15% Weight", "Benchmark Nifty 50 directional drift, India VIX regime (<15 calm bullish vs >20 high volatility caution), and domestic institutional (DII) absorption.")
    ]
    pdf.set_font('Helvetica', 'B', 7.5)
    pdf.set_fill_color(240, 244, 250)
    pdf.cell(50, 5.5, 'Quantitative Pillar', 1, 0, 'L', 1)
    pdf.cell(25, 5.5, 'Weight', 1, 0, 'C', 1)
    pdf.cell(103, 5.5, 'Specific Factors & Mathematical Inputs Evaluated', 1, 1, 'L', 1)
    pdf.set_font('Helvetica', '', 7.5)
    for p in pillars:
        pdf.cell(50, 6, p[0], 1)
        pdf.cell(25, 6, p[1], 1, 0, 'C')
        pdf.cell(103, 6, p[2], 1, 1)

    pdf.ln(2)
    pdf.subsection_title("The News Veto Rule (Section 6.6):")
    pdf.body_p(
        "Regardless of whether a stock has a perfect technical breakout or low valuation, if live news sentiment scores <= -0.40 "
        "(indicating severe regulatory orders, auditor resignations, fraud allegations, SEBI investigations, or sudden management turmoil), "
        "the stock is INSTANTLY DISQUALIFIED. The system refuses to recommend a stock facing existential headline risk."
    )

    # =========================================================================
    # SECTION 3: MATHEMATICAL ATR-14 BOUNDS
    # =========================================================================
    pdf.section_header("3. HOW THE 5-DAY TARGET IS CALCULATED (THE MATH)", "ATR-14 Volatility Grounding: Eliminating Hallucinations")
    pdf.body_p(
        "The price target is NOT an opinion. It is derived mathematically from the stock's actual trading volatility over the last 14 sessions:"
    )

    pdf.subsection_title("Formulas for the 5-Day Volatility Envelope:")
    math_rows = [
        ("True Range (TR)", "TR = max[(High_t - Low_t), |High_t - Close_t-1|, |Low_t - Close_t-1|]"),
        ("Average True Range (ATR-14)", "ATR_14 = (1 / 14) * SUM(TR_i) across 14 historical trading sessions"),
        ("5-Day Expected Target Price", "Target = CMP + (1.30 * ATR_14)"),
        ("Upper Volatility Resistance Band", "Range_High = CMP + (1.50 * ATR_14)"),
        ("Lower Support / Invalidation (SL)", "Range_Low = CMP - (1.20 * ATR_14)"),
        ("Projected Gain Percentage", "Expected Appreciation % = ((Target - CMP) / CMP) * 100")
    ]
    pdf.set_font('Helvetica', 'B', 7.5)
    pdf.set_fill_color(240, 244, 250)
    pdf.cell(56, 5.5, 'Mathematical Metric', 1, 0, 'L', 1)
    pdf.cell(122, 5.5, 'Formula Description', 1, 1, 'L', 1)
    pdf.set_font('Helvetica', '', 7.5)
    for r in math_rows:
        pdf.cell(56, 5, r[0], 1)
        pdf.cell(122, 5, r[1], 1, 1)

    pdf.ln(2)
    pdf.subsection_title("Real Worked Numerical Example (Vedanta Ltd - VEDL):")
    pdf.body_p(
        "To understand how this operates in practice, consider the top pick currently displayed on your terminal:\n"
        "- Stock: Vedanta Ltd (VEDL) on NSE\n"
        "- Current Reference Price (CMP): Rs 264.90\n"
        "- Measured 14-Day True Volatility (ATR-14): Rs 7.43\n"
        "- 5-Day Target Calculation: Target = Rs 264.90 + (1.30 * 7.43) = Rs 274.57 (+3.65%)\n"
        "- Upper Range High: Rs 264.90 + (1.50 * 7.43) = Rs 276.05 (Upper Volatility Band)\n"
        "- Lower Invalidation (Stop Loss): Rs 264.90 - (1.20 * 7.43) = Rs 256.00 (Lower Support Band)\n"
        "Notice that because VEDL's historical volatility is Rs 7.43, its expected 5-day gain is capped at +3.65%. The math prevents "
        "the system from making false promises like +20% on a stock that physically moves only Rs 7 a week."
    )

    # =========================================================================
    # SECTION 4: THE ROLE OF THE AI
    # =========================================================================
    pdf.section_header("4. THE ROLE OF THE AI: 7 SPECIALIST ANALYSTS & GROQ LLM", "Multi-Agent Committee Debate Powered by Groq (openai/gpt-oss-120b)")
    pdf.body_p(
        "Once the mathematical engine selects the top 5 stocks, the Artificial Intelligence is summoned. "
        "Connected to your active Groq Cloud key running the 120-Billion parameter 'openai/gpt-oss-120b' model, "
        "the AI simulates 7 specialized institutional desks:"
    )

    analysts = [
        ("1. Technical Analyst", "BULLISH", "Validates RSI-14 momentum, 20-DMA support, and volume breakout structure."),
        ("2. Fundamental Analyst", "ACCUMULATE", "Evaluates ROCE, balance sheet resilience, and dominant sector market share."),
        ("3. Options & Volatility Desk", "FAVORABLE RANGE", "Analyzes implied volatility smile and options strike support levels."),
        ("4. News & Catalysts Desk", "POSITIVE MOMENTUM", "Evaluates recent quarterly reports, contracts, and expansion timelines."),
        ("5. Sentiment & Media Desk", "BULLISH", "Measures social and financial media sentiment and regulatory disclosure health."),
        ("6. Sector Rotation Desk", "OVERWEIGHT", "Measures relative strength index against benchmark Nifty 50."),
        ("7. Risk Manager Desk", "CALIBRATED RISK", "Establishes position sizing (max 5-8% allocation) and downside invalidation.")
    ]
    pdf.set_font('Helvetica', 'B', 7.5)
    pdf.set_fill_color(240, 244, 250)
    pdf.cell(50, 5.5, 'Specialist Analyst Desk', 1, 0, 'L', 1)
    pdf.cell(32, 5.5, 'Committee Stance', 1, 0, 'C', 1)
    pdf.cell(96, 5.5, 'Institutional Focus & Responsibilities', 1, 1, 'L', 1)
    pdf.set_font('Helvetica', '', 7.5)
    for a in analysts:
        pdf.cell(50, 5.2, a[0], 1)
        pdf.cell(32, 5.2, a[1], 1, 0, 'C')
        pdf.cell(96, 5.2, a[2], 1, 1)

    pdf.ln(2)
    pdf.subsection_title("The Adversarial Debate Arena:")
    pdf.body_p(
        "The AI does not simply say 'buy'. It runs an adversarial debate:\n"
        "- Bull Agent: Defends the 3 strongest upside thesis points.\n"
        "- Bear Agent: Identifies the 3 primary risk factors and failure hurdles.\n"
        "- Facilitator Consensus: Synthesizes a unified verdict (e.g. 'BUY / ACCUMULATE ON DIP').\n"
        "- Calibrated Trade Plan: Delivers exact Suggested Entry Zone, Stop Loss (lower ATR band), and 5-Day Target."
    )

    # =========================================================================
    # SECTION 5: PIPELINE & ACCOUNTABILITY
    # =========================================================================
    pdf.section_header("5. STEP-BY-STEP PIPELINE: FROM UNIVERSE TO USER SCREEN", "The 10-Stage Deterministic Workflow")
    
    steps = [
        ("Stage 1", "Universe Ingestion", "Ingests 60+ constituents across Nifty 50 and Nifty 100 universe."),
        ("Stage 2", "Data Verification", "Pulls 6-month historical OHLCV data; verifies no 0.5% price discrepancies."),
        ("Stage 3", "Indicator Computation", "Calculates RSI-14, 20-DMA, ATR-14, and MACD divergence vectors."),
        ("Stage 4", "Live News RSS Scrape", "Scrapes rolling 7-day headlines via Google News RSS for each ticker."),
        ("Stage 5", "Veto Rule Filtering", "Disqualifies any scrip with sentiment <= -0.40 or severe regulatory actions."),
        ("Stage 6", "Composite Scoring", "Applies 4-pillar weights to compute score (0-100); filters for score >= 68.0."),
        ("Stage 7", "Shortlist Selection", "Selects the Top 5 unique, sector-diversified stocks with highest composite scores."),
        ("Stage 8", "ATR Bounds Math", "Calculates exact target (CMP + 1.30*ATR) and lower invalidation levels."),
        ("Stage 9", "7 AI Committee Debate", "Dispatches shortlist to Groq LLM to synthesize bull vs bear trade plans."),
        ("Stage 10", "Immutable Logging", "Saves records with immutable UUIDs to SQLite for 5th session alpha evaluation.")
    ]
    pdf.set_font('Helvetica', 'B', 7.5)
    pdf.set_fill_color(240, 244, 250)
    pdf.cell(20, 5.5, 'Stage', 1, 0, 'C', 1)
    pdf.cell(42, 5.5, 'Pipeline Phase', 1, 0, 'L', 1)
    pdf.cell(116, 5.5, 'Automated Execution Actions', 1, 1, 'L', 1)
    pdf.set_font('Helvetica', '', 7.5)
    for s in steps:
        pdf.cell(20, 5.2, s[0], 1, 0, 'C')
        pdf.cell(42, 5.2, s[1], 1, 0)
        pdf.cell(116, 5.2, s[2], 1, 1)

    pdf.ln(3)

    # Accountability Summary Box
    pdf.set_fill_color(248, 250, 252)
    pdf.rect(16, pdf.get_y(), 178, 16, 'F')
    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_text_color(15, 23, 42)
    pdf.set_xy(18, pdf.get_y() + 2)
    pdf.cell(174, 4, "ACCOUNTABILITY PROMISE: BENCHMARKED AGAINST NIFTY 50", ln=1)
    pdf.set_font('Helvetica', '', 7.5)
    pdf.set_text_color(51, 65, 85)
    pdf.set_x(18)
    pdf.multi_cell(174, 3.6, "At the close of the 5th trading session, every forecast is compared against actual market closing prices and the Nifty 50 baseline return to compute real institutional Alpha. If the stock beats the index, it is graded a HIT; if it underperforms, it is recorded as a MISS. Past predictions cannot be edited, deleted, or revised.")

    # Save outputs
    pdf_filename = "PredictaStock_Stock_Prediction_Engine_and_Factors_Explained.pdf"
    output_path_reports = REPORTS_DIR / pdf_filename
    output_path_artifact = ARTIFACT_DIR / pdf_filename

    pdf.output(str(output_path_reports))
    pdf.output(str(output_path_artifact))

    print(f"Factors PDF Successfully Generated!")
    print(f"Reports Path: {output_path_reports}")
    print(f"Artifact Path: {output_path_artifact}")
    print(f"Total Pages: {pdf.page_no()}")
    return str(output_path_reports), str(output_path_artifact), pdf.page_no()


if __name__ == "__main__":
    build_factors_pdf()
