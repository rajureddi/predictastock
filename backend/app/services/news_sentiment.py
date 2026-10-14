"""
Financial News Ingestion & Sentiment Analysis Engine
Ingests real-time news headlines via Google News RSS for Indian Equities.
Scores sentiment (-1.0 to +1.0) and enforces Phase 1 Data Integrity:
- ZERO synthetic or fabricated fallback headlines.
- Missing news is honestly treated as empty/neutral (score = 0.0).
- Genuine deduplication by headline content.
- Catalysts and risks only populated from verified parsed headlines.
"""
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import re
from typing import List, Dict, Any, Tuple
import logging

logger = logging.getLogger(__name__)

# Key Indian financial vocabulary for high-accuracy domain scoring
POSITIVE_KEYWORDS = [
    "profit jumps", "profit surges", "revenue up", "beat estimates", "ebitda growth",
    "order win", "wins contract", "expansion", "capacity hike", "promoter buys",
    "fii buying", "rating upgrade", "target raised", "dividend hike", "bonus issue",
    "q1 beat", "q2 beat", "q3 beat", "q4 beat", "strong results", "all-time high",
    "bullish", "acquisition", "debt reduction", "margin expansion", "fda approval"
]

NEGATIVE_KEYWORDS = [
    "profit falls", "profit drops", "loss widens", "misses estimates", "tax raid",
    "sebi probe", "sebi notice", "ed raid", "fraud", "scam", "ceo resigns",
    "auditor resigns", "governance", "promoter pledge", "downgrade", "target cut",
    "margin squeeze", "penalty", "default", "bankruptcy", "legal dispute",
    "subpoena", "nclt", "strike", "plant shutdown", "guidance lowered"
]


def fetch_stock_news_rss(symbol: str, max_items: int = 5) -> List[Dict[str, Any]]:
    """
    Scrape real-time financial news for an NSE stock via Google News India RSS feed.
    Phase 1 Rule: If no news is found or network fails, returns an empty list.
    NEVER appends synthetic generic positive headlines.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    query = f"NSE+{clean_sym}+stock"
    url = f"https://news.google.com/rss/search?q={query}+when:7d&hl=en-IN&gl=IN&ceid=IN:en"
    
    news_items = []
    seen_titles = set()
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        with urllib.request.urlopen(req, timeout=6) as response:
            xml_data = response.read()
            root = ET.fromstring(xml_data)
            
            for item in root.findall('.//item'):
                if len(news_items) >= max_items:
                    break
                title = item.find('title').text if item.find('title') is not None else ""
                link = item.find('link').text if item.find('link') is not None else ""
                pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ""
                source_elem = item.find('source')
                source = source_elem.text if source_elem is not None else "Financial Media"
                
                # Clean title (Google News formats as 'Title - Source')
                clean_title = re.sub(r' - [^-]+$', '', title).strip()
                if not clean_title or clean_title in seen_titles:
                    continue
                seen_titles.add(clean_title)
                
                news_items.append({
                    "title": clean_title,
                    "source": source,
                    "link": link,
                    "pub_date": pub_date,
                    "symbol": clean_sym,
                    "retrieved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
                })
    except Exception as e:
        logger.warning(f"Could not fetch RSS news for {symbol}: {e}")
        
    # Return genuine list (empty if network offline or no news)
    return news_items


def analyze_sentiment(news_items: List[Dict[str, Any]]) -> Tuple[float, str, List[str], List[str]]:
    """
    Analyze headlines using financial sentiment lexicon.
    Phase 1 Rule:
    - If no headlines exist, return score 0.0, label 'No Recent Headlines', empty lists.
    - Zero keyword matches return exactly 0.0 (Neutral), not an artificial positive bias.
    - Catalysts and risks are populated strictly from matching genuine headlines.
    """
    if not news_items:
        return 0.0, "No Recent Headlines", [], []
    
    total_pos = 0
    total_neg = 0
    catalysts = []
    risks = []
    
    for item in news_items:
        text = item["title"].lower()
        pos_match = [k for k in POSITIVE_KEYWORDS if k in text]
        neg_match = [k for k in NEGATIVE_KEYWORDS if k in text]
        
        if pos_match:
            total_pos += len(pos_match)
            catalysts.append(f"{item['title']} (Source: {item['source']})")
        if neg_match:
            total_neg += len(neg_match)
            risks.append(f"Risk Alert: {item['title']} (Source: {item['source']})")
            
    # Calculate score objectively
    if total_pos == 0 and total_neg == 0:
        score = 0.0
        label = "Neutral (No Sentiment Keywords Detected)"
    else:
        diff = total_pos - total_neg
        score = round(max(min(diff * 0.35, 1.0), -1.0), 2)
        
        if score >= 0.35:
            label = "Positive"
        elif score <= -0.35:
            label = "Negative"
        elif total_pos > 0 and total_neg > 0:
            label = "Mixed / Conflicting Signals"
        else:
            label = "Neutral"
            
    return score, label, catalysts, risks
