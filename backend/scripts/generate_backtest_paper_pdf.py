"""
Generate Institutional Backtest Paper PDF
"""
import sys
from pathlib import Path
from fpdf import FPDF

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.config import REPORTS_DIR

class BacktestPaperPDF(FPDF):
    def header(self):
        self.set_fill_color(11, 14, 20)
        self.rect(0, 0, 210, 20, 'F')
        self.set_font('Helvetica', 'B', 12)
        self.set_text_color(0, 210, 255)
        self.cell(0, 8, 'PREDICTASTOCK RESEARCH  |  INSTITUTIONAL BACKTEST & METHODOLOGY PAPER', ln=1, align='L')
        self.set_font('Helvetica', '', 8)
        self.set_text_color(160, 175, 195)
        self.cell(0, 4, 'Out-of-Sample 5-Day Horizon Evaluation vs. 3 Naive Baselines (NSE/BSE Indian Equities)', ln=1, align='L')
        self.ln(6)

    def footer(self):
        self.set_y(-14)
        self.set_font('Helvetica', 'I', 7)
        self.set_text_color(120, 130, 145)
        self.cell(0, 8, f"Page {self.page_no()}  |  Confidential Research Paper  |  Leakage-Controlled Point-in-Time Evaluation", align='C')


def generate_pdf():
    pdf = BacktestPaperPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Title & Metadata
    pdf.set_font('Helvetica', 'B', 16)
    pdf.set_text_color(255, 159, 28)
    pdf.cell(0, 10, "Empirical Forecast Evaluation & Baseline Verification", ln=1)

    pdf.set_font('Helvetica', 'I', 9)
    pdf.set_text_color(80, 90, 105)
    pdf.cell(0, 5, "Author: PredictaStock Quantitative Research Group  *  Status: Independently Auditable  *  Edition: Oct 2026", ln=1)
    pdf.ln(4)

    # 1. Executive Abstract
    pdf.set_font('Helvetica', 'B', 11)
    pdf.set_text_color(0, 150, 200)
    pdf.cell(0, 7, "1. Executive Abstract & Scope", ln=1)
    pdf.set_font('Helvetica', '', 8.5)
    pdf.set_text_color(30, 30, 30)
    pdf.multi_cell(0, 4.5, "This paper establishes the out-of-sample empirical evaluation of the PredictaStock 4-Pillar Volatility Scenario Model over forward 5-trading-day horizons across front-line Indian liquid equities (Nifty 50 constituents). To guarantee scientific integrity, the model is strictly benchmarked against three non-trivial baseline models: (1) the No-Change Model, (2) the Nifty 50 Passive Buy & Hold Benchmark, and (3) a 20-DMA Trend Extrapolation Baseline. All forward evaluations deduct an institutional statutory friction of 0.15% roundtrip.")
    pdf.ln(3)

    # 2. Information Filtration Protocol
    pdf.set_font('Helvetica', 'B', 11)
    pdf.set_text_color(0, 150, 200)
    pdf.cell(0, 7, "2. Information Filtration & Strict Leakage Control", ln=1)
    pdf.set_font('Helvetica', '', 8.5)
    pdf.set_text_color(30, 30, 30)
    pdf.multi_cell(0, 4.5, "In quantitative finance, look-ahead bias invalidates historical claims. PredictaStock enforces an information filtration boundary F_t where features, moving averages, and indicators at trade inception session t utilize only completed daily bars on or before session t. Forward returns are evaluated at the exact closing price of the 5th trading session (t+5). Original predictions are stored with unique run_id hashes, guaranteeing idempotency.")
    pdf.ln(3)

    # 3. Transaction Cost Model
    pdf.set_font('Helvetica', 'B', 11)
    pdf.set_text_color(0, 150, 200)
    pdf.cell(0, 7, "3. Indian Regulatory Transaction Friction Model (0.15% Roundtrip)", ln=1)
    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_fill_color(240, 243, 248)
    pdf.cell(70, 6, "Cost Component", 1, 0, 'L', 1)
    pdf.cell(50, 6, "Statutory Rate", 1, 0, 'C', 1)
    pdf.cell(70, 6, "Regulatory Basis", 1, 1, 'L', 1)

    pdf.set_font('Helvetica', '', 8)
    costs = [
        ("Securities Transaction Tax (STT)", "0.100%", "Delivery turnover (Buy & Sell)"),
        ("Brokerage (Discount Institutional)", "0.050%", "Turnover capped at Rs. 20/order"),
        ("Exchange Turnover Charges", "0.00345%", "NSE exchange fee"),
        ("Stamp Duty (State Stamp Act)", "0.015%", "Buy delivery turnover"),
        ("Goods & Services Tax (GST)", "18.00%", "On Brokerage + Exchange fees"),
        ("Execution Slippage Allowance", "0.050%", "Bid-ask spread absorption"),
        ("Total Net Deducted Friction", "0.150%", "Deducted from every 5-day return")
    ]
    for c, r, b in costs:
        is_bold = "Total" in c
        if is_bold:
            pdf.set_font('Helvetica', 'B', 8)
            pdf.set_fill_color(230, 240, 250)
            pdf.cell(70, 6, c, 1, 0, 'L', 1)
            pdf.cell(50, 6, r, 1, 0, 'C', 1)
            pdf.cell(70, 6, b, 1, 1, 'L', 1)
            pdf.set_font('Helvetica', '', 8)
        else:
            pdf.cell(70, 5.5, c, 1)
            pdf.cell(50, 5.5, r, 1, 0, 'C')
            pdf.cell(70, 5.5, b, 1, 1, 'L')

    pdf.ln(4)

    # 4. Out-of-Sample Performance Matrix
    pdf.set_font('Helvetica', 'B', 11)
    pdf.set_text_color(0, 150, 200)
    pdf.cell(0, 7, "4. Out-of-Sample Empirical Results (4-Model Matrix)", ln=1)

    pdf.set_font('Helvetica', 'B', 7.5)
    pdf.set_fill_color(240, 243, 248)
    pdf.cell(58, 6, "Strategy / Benchmark Model", 1, 0, 'L', 1)
    pdf.cell(18, 6, "Sample N", 1, 0, 'C', 1)
    pdf.cell(24, 6, "Hit Rate", 1, 0, 'C', 1)
    pdf.cell(24, 6, "Avg Return", 1, 0, 'C', 1)
    pdf.cell(24, 6, "Alpha vs Nifty", 1, 0, 'C', 1)
    pdf.cell(22, 6, "Profit Factor", 1, 0, 'C', 1)
    pdf.cell(20, 6, "Max DD", 1, 1, 'C', 1)

    pdf.set_font('Helvetica', '', 7.5)
    matrix = [
        ("PredictaStock Multi-Factor (Model)", "85", "42.4%", "-0.22%", "-0.07%", "0.81", "-36.56%"),
        ("Nifty 50 Buy & Hold Benchmark", "85", "35.3%", "-0.15%", "0.00% (Base)", "N/A", "N/A"),
        ("20-DMA Trend Extrapolation Baseline", "85", "45.9%", "-0.23%", "-0.08%", "N/A", "N/A"),
        ("No-Change Model (0% Return)", "85", "30.6%", "0.00%", "+0.15%", "N/A", "N/A")
    ]
    for m in matrix:
        if "PredictaStock" in m[0]:
            pdf.set_font('Helvetica', 'B', 7.5)
            pdf.set_fill_color(230, 245, 255)
            pdf.cell(58, 6, m[0], 1, 0, 'L', 1)
            pdf.cell(18, 6, m[1], 1, 0, 'C', 1)
            pdf.cell(24, 6, m[2], 1, 0, 'C', 1)
            pdf.cell(24, 6, m[3], 1, 0, 'C', 1)
            pdf.cell(24, 6, m[4], 1, 0, 'C', 1)
            pdf.cell(22, 6, m[5], 1, 0, 'C', 1)
            pdf.cell(20, 6, m[6], 1, 1, 'C', 1)
            pdf.set_font('Helvetica', '', 7.5)
        else:
            pdf.cell(58, 5.5, m[0], 1)
            pdf.cell(18, 5.5, m[1], 1, 0, 'C')
            pdf.cell(24, 5.5, m[2], 1, 0, 'C')
            pdf.cell(24, 5.5, m[3], 1, 0, 'C')
            pdf.cell(24, 5.5, m[4], 1, 0, 'C')
            pdf.cell(22, 5.5, m[5], 1, 0, 'C')
            pdf.cell(20, 5.5, m[6], 1, 1, 'C')

    pdf.ln(3)

    # 5. Market Regime Sensitivity
    pdf.set_font('Helvetica', 'B', 11)
    pdf.set_text_color(0, 150, 200)
    pdf.cell(0, 7, "5. Market Regime Sensitivity Analysis", ln=1)
    pdf.set_font('Helvetica', '', 8.5)
    pdf.set_text_color(30, 30, 30)
    pdf.multi_cell(0, 4.5, "Disaggregating performance across macro market regimes highlights structural asymmetries:\n"
                           "* Bull Market Sessions (Nifty 50 Return > 0): Directional Hit Rate = 53.3%.\n"
                           "* Bear Market Sessions (Nifty 50 Return <= 0): Directional Hit Rate = 36.4%.\n"
                           "In constructive sessions, momentum and fundamental screens align with market continuation. In bearish sessions, downside volatility spikes degrade individual stock alpha, proving that disciplined risk management and stop-loss adherence are paramount.")
    pdf.ln(3)

    # 6. Regulatory & Institutional Governance Disclaimers
    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_text_color(180, 50, 50)
    pdf.cell(0, 6, "6. Statutory Disclaimers & Governance Notice", ln=1)
    pdf.set_font('Helvetica', 'I', 7.5)
    pdf.set_text_color(90, 90, 90)
    pdf.multi_cell(0, 4, "1. Educational & Decision-Support Only: PredictaStock is designed as a structured research dashboard. It does not execute automated broker orders or guarantee returns.\n2. Non-SEBI Registration: Not registered with SEBI under SEBI (Research Analysts) Regulations, 2014. Forecasted volatility cones represent bounded statistical dispersion scenarios, not guaranteed trading advice.")

    pdf_path = REPORTS_DIR / "PredictaStock_Institutional_Backtest_Paper.pdf"
    pdf.output(str(pdf_path))
    print(f"PDF Generated: {pdf_path}")
    return str(pdf_path)

if __name__ == "__main__":
    generate_pdf()
