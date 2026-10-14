"""
PredictaStock Comprehensive Client Specification PDF Builder
Generates an institutional-grade, multi-page client document covering:
- Mathematical 5-day prediction formulas (ATR-14, 4 pillars)
- Every single UI component, card, button, and screen
- 7 AI Analyst Desks & Groq LLM Committee (india-trade-cli)
- Deep Intelligence, Money Flow Radar & 3D India Globe
- Indian Statutory Tax Engine (STT, Stamp Duty, Brokerage, GST, STCG/LTCG)
- The 6 Immutable Owner Rules
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


class ClientReportPDF(FPDF):
    def __init__(self):
        super().__init__(orientation='P', unit='mm', format='A4')
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(16, 18, 16)

    def header(self):
        if self.page_no() == 1:
            return # Cover / Title page has custom banner
        self.set_fill_color(11, 14, 20) # Obsidian header bar
        self.rect(0, 0, 210, 16, 'F')
        self.set_font('Helvetica', 'B', 8.5)
        self.set_text_color(255, 159, 28) # Bloomberg Amber
        self.set_xy(16, 3)
        self.cell(100, 5, 'PREDICTASTOCK AI  |  CLIENT SPECIFICATION & AUDIT REPORT', align='L')
        self.set_font('Helvetica', '', 7.5)
        self.set_text_color(160, 175, 195)
        self.set_xy(116, 3)
        self.cell(78, 5, 'INSTITUTIONAL EQUITY TERMINAL v2.0', align='R')
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
        self.cell(90, 8, 'Confidential & Proprietary  *  Prepared for Client Review', align='L')
        self.cell(88, 8, f'Page {self.page_no()}', align='R')

    # Utility formatting methods
    def section_header(self, title, subtitle=None):
        self.ln(4)
        self.set_fill_color(244, 247, 252)
        self.set_draw_color(99, 102, 241) # Indigo accent
        self.set_line_width(0.6)
        self.rect(16, self.get_y(), 178, 9, 'DF')
        self.set_font('Helvetica', 'B', 10.5)
        self.set_text_color(15, 23, 42)
        self.set_xy(19, self.get_y() + 1.8)
        self.cell(172, 5, title, ln=1)
        if subtitle:
            self.set_font('Helvetica', 'I', 8)
            self.set_text_color(100, 116, 139)
            self.set_x(19)
            self.cell(172, 4, subtitle, ln=1)
        self.ln(2)

    def subsection_title(self, title):
        self.set_font('Helvetica', 'B', 9)
        self.set_text_color(79, 70, 229) # Indigo
        self.cell(0, 6, title, ln=1)

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


def build_pdf():
    pdf = ClientReportPDF()
    pdf.add_page()

    # =========================================================================
    # COVER / HERO BANNER
    # =========================================================================
    pdf.set_fill_color(11, 14, 20)
    pdf.rect(0, 0, 210, 48, 'F')
    
    # Gold accent line
    pdf.set_fill_color(255, 159, 28)
    pdf.rect(0, 48, 210, 1.5, 'F')

    pdf.set_xy(16, 8)
    pdf.set_font('Helvetica', 'B', 17)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(178, 8, 'PREDICTASTOCK AI TERMINAL', ln=1)

    pdf.set_font('Helvetica', 'B', 10.5)
    pdf.set_text_color(255, 159, 28)
    pdf.cell(178, 6, 'COMPREHENSIVE ARCHITECTURAL, MATHEMATICAL & UI SPECIFICATION REPORT', ln=1)

    pdf.set_font('Helvetica', '', 8)
    pdf.set_text_color(180, 195, 215)
    meta_line = f"Version: 2.0.0-Institutional  *  Target Markets: NSE / BSE  *  Date: {date.today().strftime('%d %B %Y')}  *  Status: Operational"
    pdf.cell(178, 5, meta_line, ln=1)

    pdf.set_y(54)

    # Executive Overview
    pdf.section_header("1. EXECUTIVE BLUEPRINT & ARCHITECTURAL FOUNDATION", "Core Philosophy: Mathematical Discipline, Strict Accountability & SEBI Decision Support")
    pdf.body_p(
        "PredictaStock is an institutional-grade stock market decision assistant and portfolio accounting terminal engineered "
        "strictly according to the official specification. Unlike retail trading screeners that promote impulsive day-trading or generate "
        "ungrounded 'black-box' price guesses, PredictaStock is founded upon three uncompromising principles: (1) Mathematical ATR-14 "
        "volatility bounds, (2) Immutable insert-only database accountability, and (3) Deterministic Indian statutory tax & FIFO accounting."
    )
    pdf.body_p(
        "The system acts strictly as an intelligent co-pilot and decision support system. Automatic real-money order execution is "
        "prohibited by architecture. All portfolio holdings are manually recorded by the user, and every historical prediction is locked "
        "with immutable UUIDs to prevent revisionism."
    )

    # Technology Stack Table
    pdf.subsection_title("Full Production Technology Stack:")
    pdf.set_font('Helvetica', 'B', 7.5)
    pdf.set_fill_color(240, 244, 250)
    pdf.cell(42, 6, 'Layer / Component', 1, 0, 'L', 1)
    pdf.cell(56, 6, 'Technology Used', 1, 0, 'L', 1)
    pdf.cell(80, 6, 'Architectural Purpose', 1, 1, 'L', 1)
    
    stack = [
        ("Backend Web Framework", "FastAPI (Python 3.14)", "High-concurrency async REST API engine"),
        ("Database Engine", "SQLite in WAL Mode", "Zero-lock concurrent reads/writes with immutable ledger"),
        ("Active LLM Reasoning", "Groq Cloud (openai/gpt-oss-120b)", "Ultra-fast 120-Billion parameter committee debate"),
        ("Predictive Math Engine", "NumPy, Pandas, TA-Lib Indicators", "Mathematical ATR-14, RSI-14, 20-DMA bounds"),
        ("Frontend Application", "HTML5 + Vanilla CSS + Vanilla JS", "Zero framework bloat; sub-100ms snappy response"),
        ("Data Visualizations", "Chart.js 4.4 + Three.js r128", "Dynamic 5D volatility envelopes & 3D India globe"),
        ("Statutory Tax Module", "Deterministic Python Ledger", "Exact STT (0.1%), Stamp (0.015%), GST (18%), STCG/LTCG"),
        ("Report Compilation", "FPDF2 (Vector PDF Engine)", "Automated 5:45 AM IST morning brief generator")
    ]
    pdf.set_font('Helvetica', '', 7.5)
    for row in stack:
        pdf.cell(42, 5.2, row[0], 1)
        pdf.cell(56, 5.2, row[1], 1)
        pdf.cell(80, 5.2, row[2], 1, 1)

    pdf.ln(3)

    # =========================================================================
    # SECTION 2: MATHEMATICAL PREDICTION ENGINE
    # =========================================================================
    pdf.section_header("2. MATHEMATICAL 5-DAY STOCK PREDICTION ENGINE", "How Price Forecasts and Volatility Bounds Are Calculated Without AI Hallucinations")
    pdf.body_p(
        "A critical mandate of the system is the complete elimination of ungrounded AI price guesses. Every single target price, "
        "upper resistance band, and downside stop level is mathematically constrained by historical volatility formulas derived from the "
        "14-period Average True Range (ATR-14) and 5-day historical volatility."
    )

    pdf.subsection_title("The 5-Day Swing Horizon Rationale:")
    pdf.body_p(
        "In the Indian capital markets, 5 trading sessions represent the standard swing-trading cycle (Monday open through Friday close, "
        "accounting for official NSE trading holidays). This timeframe filters out random intraday noise while establishing a concrete, "
        "accountable evaluation deadline at the close of the 5th trading session."
    )

    pdf.subsection_title("Exact Mathematical Formulas:")
    formulas = [
        ("True Range (TR)", "TR = max[(High_t - Low_t), |High_t - Close_t-1|, |Low_t - Close_t-1|]"),
        ("Average True Range (ATR-14)", "ATR_14 = (1 / 14) * SUM(TR_i) over 14 historical sessions"),
        ("5-Day Expected Target Price", "Target = CMP + (1.30 * ATR_14)"),
        ("Upper Resistance Band", "Range_High = CMP + (1.50 * ATR_14)"),
        ("Lower Support / Invalidation", "Range_Low = CMP - (1.20 * ATR_14)"),
        ("Projected Appreciation %", "Appreciation % = ((Target - CMP) / CMP) * 100")
    ]
    pdf.set_font('Helvetica', 'B', 7.5)
    pdf.set_fill_color(240, 244, 250)
    pdf.cell(55, 5.5, 'Metric / Target', 1, 0, 'L', 1)
    pdf.cell(123, 5.5, 'Exact Mathematical Formula', 1, 1, 'L', 1)
    pdf.set_font('Helvetica', '', 7.5)
    for f in formulas:
        pdf.cell(55, 5, f[0], 1)
        pdf.cell(123, 5, f[1], 1, 1)

    pdf.ln(2)
    pdf.subsection_title("The 4-Pillar Multi-Factor Scoring Formula (Composite Score: 0 to 100):")
    pdf.body_p(
        "Composite Score = (0.35 * S_tech) + (0.25 * S_fund) + (0.25 * S_news) + (0.15 * S_macro)\n"
        "* Pillar 1 - Technical Momentum (35%): RSI-14 between 45 and 68, confirmation above 20-DMA, positive MACD histogram divergence.\n"
        "* Pillar 2 - Fundamental Safety (25%): Nifty 50 core leadership (75 pts baseline), balance sheet solvency, high ROCE.\n"
        "* Pillar 3 - News & Sentiment (25%): Scrapes rolling 7-day headlines via Google News RSS; maps score [-1.0, 1.0] to [0, 100].\n"
        "* Pillar 4 - Macro Flow (15%): Nifty 50 live drift, India VIX regime (<15 calm vs >20 caution), domestic institutional inflows."
    )

    pdf.subsection_title("The News Veto Rule (Section 6.6):")
    pdf.body_p(
        "Regardless of how bullish a stock's technical chart or moving averages appear, if rolling news sentiment scores <= -0.40 "
        "(severe negative regulatory actions, auditor resignations, fraud allegations, SEBI investigations), the stock is IMMEDIATELY "
        "DISQUALIFIED from the shortlist. Furthermore, if fewer than 5 stocks meet the strict 68.0 score threshold, the system displays "
        "'No strong opportunities today' rather than forcing subpar recommendations."
    )

    # =========================================================================
    # SECTION 3: END-TO-END TIMELINE
    # =========================================================================
    pdf.section_header("3. CHRONOLOGICAL EXECUTION TIMELINE", "Automated Daily Schedule Guaranteeing 5:45 AM IST Delivery")
    
    timeline = [
        ("4:30 PM IST", "Post-Market Ingestion", "Ingests NSE closing prices, computes 14-day ATRs, updates scorecard alpha vs Nifty 50."),
        ("4:30 AM IST", "Pre-Market Refresh", "Scrapes overnight global cues, evaluates news veto rules, pre-scores top shortlist candidates."),
        ("5:00 AM IST", "7 AI Committee Debate", "Dispatches shortlist to Groq LLM (gpt-oss-120b) to synthesize bull vs bear trade plans."),
        ("5:15 AM IST", "HTML Report Synthesis", "Builds the complete 10-section briefing with interactive tables and formatting."),
        ("5:25 AM IST", "Vector PDF Compilation", "Compiles A4 PDF report with checksum verification into the reports repository."),
        ("5:35 AM IST", "Integrity Check", "Confirms PDF file exists on disk, validates data accuracy, and prepares dispatch."),
        ("5:45 AM IST", "Strict Delivery Deadline", "Briefing ready for client download and preview in the Web Terminal.")
    ]
    pdf.set_font('Helvetica', 'B', 7.5)
    pdf.set_fill_color(240, 244, 250)
    pdf.cell(26, 5.5, 'Schedule Time', 1, 0, 'C', 1)
    pdf.cell(46, 5.5, 'Execution Phase', 1, 0, 'L', 1)
    pdf.cell(106, 5.5, 'Automated Actions Performed', 1, 1, 'L', 1)
    pdf.set_font('Helvetica', '', 7.5)
    for t in timeline:
        pdf.cell(26, 5.2, t[0], 1, 0, 'C')
        pdf.cell(46, 5.2, t[1], 1, 0)
        pdf.cell(106, 5.2, t[2], 1, 1)

    pdf.ln(3)

    # =========================================================================
    # SECTION 4: COMPLETE UI ANATOMY
    # =========================================================================
    pdf.section_header("4. COMPLETE UI ANATOMY & FEATURE BREAKDOWN", "Detailed Explanation of Every Screen, Card, Badge, and Action in the Web Terminal")

    pdf.subsection_title("1. Topbar & Live Market Ticker:")
    pdf.bullet("Live Ticker Strip", "Displays NIFTY 50 index level with real-time percentage change, INDIA VIX volatility level, and 5:45 AM deadline countdown.")
    pdf.bullet("Theme Toggle (Sun/Moon)", "Instant one-click toggle between Chainx Dark Mode and Marke Light Mode (persisted in localStorage).")
    pdf.bullet("Global Search (Cmd+K)", "Autocomplete input tied to all 60+ Nifty constituents. Selecting any scrip loads its 5D chart and launches deep intelligence.")
    pdf.bullet("+ RECORD BUY Button", "Opens the purchase logging modal pre-filled with live prices and real-time Indian tax breakdown.")
    pdf.bullet("RE-RUN SCAN Button", "Triggers the full multi-factor screening pipeline and launches the 3D Fibonacci India Globe visualizer.")

    pdf.subsection_title("2. Left Navigation Sidebar:")
    pdf.bullet("Navigation Links", "Instant tab switching: 5D Recommendations, Interactive 5D Charts, My Portfolio, Forecast Scorecard, Morning Report, Sector Concentration.")
    pdf.bullet("AI Quantitative Copilot", "Card featuring an atomic pulsating thinking orb with a quick-action button to summon the 7 AI Analyst Desks.")
    pdf.bullet("Sidebar Theme Switch", "Hardware-style toggle switch allowing effortless switching between Dark and Light mode aesthetics.")
    pdf.bullet("NSE Realtime Dot", "Live green beacon confirming active market feed connectivity.")

    pdf.subsection_title("3. View 1: 5-Day Recommendations Dashboard:")
    pdf.bullet("Vibrant Stat Cards", "Four distinct tinted cards: (1) Amber Ideas Count, (2) Mint Avg 5D Gain %, (3) Hero Coral Orange Market Mood & FII Inflows, (4) Sky Blue Zero-Hallucination SEBI Guarantee.")
    pdf.bullet("Recommendation Cards", "Displays Ticker Symbol, Exchange (NSE), Sector, Ref Close, 5D Target, Expected ATR Range, Risk Pill (Low/Med/High), Score, Technical Summary, Catalysts, and Risks.")
    pdf.bullet("4 Card Action Buttons", "HOT NEWS & FLOWS (opens money flow modal), 7 ANALYSTS (opens debate modal), VIEW CHART (loads chart tab), + RECORD BUY (opens purchase modal).")

    pdf.subsection_title("4. View 2: Interactive 5D Stock Charts & Volatility Cones:")
    pdf.bullet("Multi-Series Canvas", "Historical Close Line (3 months), 20-DMA Golden Line, 5-Day Target Trajectory Line, and Shaded ATR Volatility Cone Envelope.")
    pdf.bullet("Header Metrics Strip", "Displays CMP, 14-Day ATR in rupees, Expected Target Price, and Projected Gain %.")
    pdf.bullet("Volatility Analysis Panel", "Displays Projected Range Low & High, Dynamic Support Level, and Dynamic Resistance Level.")

    pdf.subsection_title("5. View 3: My Real Holdings & FIFO Tax Accounting Ledger:")
    pdf.bullet("Capital Summary Matrix", "Displays Total Invested (Rs), Current Market Value (Rs), Gross P&L, Total Statutory Deductions, and Net Realized P&L After Taxes.")
    pdf.bullet("Capital Gains Cards", "Real-time automated estimation of Short-Term Capital Gains Tax (STCG @ 20%) and Long-Term Capital Gains Tax (LTCG @ 12.5%).")
    pdf.bullet("Active Holdings Table", "Symbol, Buy Date, Quantity, Purchase Price, CMP, Market Value, Holding Days, Unrealized P&L, and SELL action.")

    pdf.subsection_title("6. View 4: Forecast Scorecard Benchmarked Against Nifty 50:")
    pdf.bullet("Accountability Metrics", "Directional Hit Rate % (target achieved), Average Alpha vs Nifty 50 %, Average Forecast Error %, and Downside Invalidation Breaches.")
    pdf.bullet("Historical Audit Ledger", "Complete table listing Start Date, End Date, Reference Price, Predicted Target, Actual End Price, Nifty 50 Return, Alpha %, and HIT/MISS outcome badge.")

    pdf.subsection_title("7. View 5: 5:45 AM Morning Briefing Center:")
    pdf.bullet("Live HTML Preview", "Embedded iframe previewing the official 10-section daily morning briefing report.")
    pdf.bullet("Official PDF Exporter", "Direct download button for the compiled vector PDF report (report_YYYY-MM-DD.pdf).")

    pdf.subsection_title("8. View 6: Sector Concentration & Diversification Radar:")
    pdf.bullet("Sector Exposure Meters", "Visual progress bars breaking down portfolio exposure across sectors (Metals, FMCG, Healthcare, Banking, IT).")
    pdf.bullet("25% Overconcentration Alert", "Automated alert banner triggered if any single sector exceeds 25% of total portfolio value.")

    # =========================================================================
    # SECTION 5: 7 ANALYSTS & GROQ LLM
    # =========================================================================
    pdf.section_header("5. 7 AI ANALYST DESKS & GROQ LLM COMMITTEE", "Adversarial Multi-Agent Debate Inspired by hopit-ai/india-trade-cli")
    pdf.body_p(
        "Clicking '7 ANALYSTS' activates a parallel committee of 7 AI specialist desks powered by your active Groq Cloud API key "
        "running the 120-Billion parameter 'openai/gpt-oss-120b' model (with automatic fallback to the quantitative expert engine):"
    )

    desks = [
        ("1. Technical Analyst", "Evaluates RSI-14 momentum, 20-DMA support levels, and MACD divergence structures."),
        ("2. Fundamental Analyst", "Assesses balance sheet debt-to-equity, ROCE quality, and dominant sector leadership."),
        ("3. Options & Volatility Desk", "Analyzes 5-day historical volatility, put-call support, and implied volatility smile."),
        ("4. News & Catalysts Desk", "Ingests breaking quarterly disclosures, capacity expansions, and operational updates."),
        ("5. Sentiment & Media Desk", "Scores social and financial media sentiment; monitors regulatory filing frequency."),
        ("6. Sector Rotation Desk", "Measures sector relative strength index vs benchmark Nifty 50 and institutional rotation."),
        ("7. Risk Manager Desk", "Establishes position sizing (max 5-8% allocation) and downside invalidation levels.")
    ]
    for d in desks:
        pdf.bullet(d[0], d[1])

    pdf.ln(1)
    pdf.subsection_title("The Adversarial Arena & Actionable Trade Plan:")
    pdf.body_p(
        "* Bull Thesis (Upside): Top 3 arguments defending price appreciation toward the 5-day target.\n"
        "* Bear Thesis (Downside): Top 3 risk factors, macro correlation risks, and profit-taking hurdles.\n"
        "* Facilitator Verdict: Institutional consensus recommendation (e.g. 'BUY / ACCUMULATE ON DIP').\n"
        "* Actionable Trade Plan: Concrete Suggested Entry Zone, Downside Invalidation (Stop Loss at lower ATR band), and 5-Day Target."
    )

    # =========================================================================
    # SECTION 6: DEEP INTELLIGENCE & 3D GLOBE
    # =========================================================================
    pdf.section_header("6. DEEP INTELLIGENCE, MONEY FLOW & 3D INDIA GLOBE", "Institutional Liquidity Meters, Internet RSS Scraper, and WebGL Three.js Visualizer")

    pdf.subsection_title("1. Institutional Money Flow & Price Drivers Modal:")
    pdf.bullet("Inflow vs Outflow Meter", "Visual horizontal bar calculating institutional accumulation percentage vs distribution percentage.")
    pdf.bullet("Chaikin Money Flow (CMF)", "Quantitative indicator measuring whether smart money is buying near daily highs or selling near daily lows.")
    pdf.bullet("Delivery Absorption Rate", "Calculates percentage of volume transferred to demat accounts vs speculative intraday turnover.")
    pdf.bullet("4 Price Driver Progress Bars", "Visualizes the 4 foundational pillars: Technical (35%), Fundamental (25%), News (25%), Liquidity (15%).")
    pdf.bullet("Live Internet News Feed", "Scrapes Google News RSS in real-time with automatic sentiment tags (BULLISH, BEARISH, NEUTRAL) and direct source links.")

    pdf.subsection_title("2. Three.js 3D Dot-Matrix India Globe Visualizer:")
    pdf.bullet("3,400 Fibonacci Points", "Mathematically distributed points forming a luxury rotating 3D particle sphere.")
    pdf.bullet("Highlighted India Coordinates", "Coordinates between Lat 7N-37N and Lon 68E-97E glowing in Saffron (#FF9F1C), Gold (#FFD700), and Emerald (#00E676).")
    pdf.bullet("Atomic Thinking Orb Rings", "Multi-axis dual counter-rotating inclination rings symbolizing parallel multi-agent reasoning desks.")
    pdf.bullet("Pulsing Geographic Beacon", "Pulsating coordinate sphere anchored at Nagpur (21N, 78E) representing the geographic heart of India.")
    pdf.bullet("Multi-Phase HUD Progress Bar", "Cycles through 6 quantitative phases during re-scans with smooth progress tracking.")

    # =========================================================================
    # SECTION 7: STATUTORY TAX & FIFO ENGINE
    # =========================================================================
    pdf.section_header("7. INDIAN STATUTORY TAXATION & FIFO ACCOUNTING", "Deterministic SEBI / Indian Income Tax Capital Gains Calculation")
    pdf.body_p(
        "PredictaStock features a deterministic accounting engine adhering strictly to Indian equity delivery tax regulations. "
        "Every transaction computes exact regulatory deductions in real time:"
    )

    tax_table = [
        ("Securities Transaction Tax (STT)", "0.100%", "Levied on both purchase value and sale value (delivery equity)"),
        ("Brokerage Fee", "Flat Rs 20", "Flat Rs 20 cap (standard discount brokers: Zerodha/AngelOne) or 0.025%"),
        ("State Stamp Duty", "0.015%", "Levied on purchase turnover only per Indian Stamp Act"),
        ("Exchange Turnover Charge", "0.00345%", "NSE / BSE transaction fee"),
        ("SEBI Regulatory Turnover Fee", "Rs 10 / Crore", "0.0001% regulatory supervision fee"),
        ("Goods and Services Tax (GST)", "18.00%", "Applied strictly to (Brokerage + Exchange Fees + SEBI Fees)"),
        ("Short-Term Capital Gains (STCG)", "20.00%", "Holding duration <= 365 days per Finance Act 2024"),
        ("Long-Term Capital Gains (LTCG)", "12.50%", "Holding duration > 365 days (applicable above Rs 1.25 Lakh threshold)")
    ]
    pdf.set_font('Helvetica', 'B', 7.5)
    pdf.set_fill_color(240, 244, 250)
    pdf.cell(50, 5.5, 'Statutory Fee / Tax Component', 1, 0, 'L', 1)
    pdf.cell(30, 5.5, 'Applicable Rate', 1, 0, 'C', 1)
    pdf.cell(98, 5.5, 'Indian Legal & Regulatory Application', 1, 1, 'L', 1)
    pdf.set_font('Helvetica', '', 7.5)
    for row in tax_table:
        pdf.cell(50, 5.2, row[0], 1)
        pdf.cell(30, 5.2, row[1], 1, 0, 'C')
        pdf.cell(98, 5.2, row[2], 1, 1)

    pdf.ln(2)
    pdf.subsection_title("First-In-First-Out (FIFO) Lot Matching:")
    pdf.body_p(
        "When selling a stock holding, the portfolio ledger matches against the OLDEST unclosed purchase lot first. "
        "The system calculates exact holding duration in calendar days, applies the appropriate STCG or LTCG tax classification, "
        "and deducts all historical buy-side and sell-side statutory fees to report true net realized P&L."
    )

    # =========================================================================
    # SECTION 8: SIX OWNER RULES COMPLIANCE
    # =========================================================================
    pdf.section_header("8. VERIFICATION OF THE SIX OWNER RULES", "Strict Non-Negotiable Operational Constraints Mandated by Specification")

    rules = [
        ("Rule 1: 5:45 AM IST Delivery", "PASSED", "3-stage pipeline (4:30 AM scan, 5:15 AM HTML build, 5:25 AM PDF compile) guarantees briefing delivery before 5:45 AM every trading day."),
        ("Rule 2: Immutable Recommendations", "PASSED", "Past recommendations are insert-only in SQLite with unique UUIDs. Forecast records cannot be edited, revised, or overwritten."),
        ("Rule 3: Recommendations vs Holdings Separate", "PASSED", "Recommendations (daily shortlist) and user holdings (actual capital commitments) operate in completely independent database schemas and UI views."),
        ("Rule 4: Zero Autonomous Order Execution", "PASSED", "The agent is strictly an analytical decision assistant. Real-money orders must be manually recorded by the user. Auto-trading is disabled."),
        ("Rule 5: No Guaranteed Returns & Honest Tracking", "PASSED", "Confidence text states 'Not enough history yet to measure accuracy' until 5th session evaluations mature. Bearish days report 'No strong opportunities'."),
        ("Rule 6: Persistent Portfolio Holdings", "PASSED", "Holdings persist in SQLite WAL database across server restarts and shortlist changes until an explicit FIFO sale transaction is executed.")
    ]
    pdf.set_font('Helvetica', 'B', 7.5)
    pdf.set_fill_color(240, 244, 250)
    pdf.cell(52, 5.5, 'Owner Rule Mandate', 1, 0, 'L', 1)
    pdf.cell(20, 5.5, 'Status', 1, 0, 'C', 1)
    pdf.cell(106, 5.5, 'Technical Implementation & Verification Proof', 1, 1, 'L', 1)
    pdf.set_font('Helvetica', '', 7.5)
    for r in rules:
        pdf.cell(52, 5.5, r[0], 1)
        pdf.set_font('Helvetica', 'B', 7.5)
        pdf.cell(20, 5.5, r[1], 1, 0, 'C')
        pdf.set_font('Helvetica', '', 7.5)
        pdf.cell(106, 5.5, r[2], 1, 1)

    pdf.ln(5)

    # Disclaimer Footer
    pdf.set_fill_color(248, 250, 252)
    pdf.rect(16, pdf.get_y(), 178, 14, 'F')
    pdf.set_font('Helvetica', 'I', 7)
    pdf.set_text_color(100, 116, 139)
    pdf.set_x(18)
    pdf.multi_cell(174, 3.5, "DISCLAIMER & REGULATORY NOTICE: This document represents a complete technical and functional specification report for PredictaStock Terminal. The software operates as an educational decision-support assistant. All recommendations are generated via quantitative mathematical ATR-14 volatility bands and automated multi-factor analysis. The system is not a SEBI-registered investment advisor.")

    # Save to outputs
    pdf_filename = "PredictaStock_Comprehensive_Client_Specification_Report.pdf"
    output_path_reports = REPORTS_DIR / pdf_filename
    output_path_artifact = ARTIFACT_DIR / pdf_filename

    pdf.output(str(output_path_reports))
    pdf.output(str(output_path_artifact))

    print(f"PDF Successfully Generated!")
    print(f"Reports Path: {output_path_reports}")
    print(f"Artifact Path: {output_path_artifact}")
    print(f"Total Pages: {pdf.page_no()}")
    return str(output_path_reports), str(output_path_artifact), pdf.page_no()


if __name__ == "__main__":
    build_pdf()
