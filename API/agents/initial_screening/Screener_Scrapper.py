"""
ScreenerScraper: A respectful scraper for Screener.in that returns
financial data in the same format as the yfinance GetFinanceValues wrapper.

Respects:
  - robots.txt (checked on first use, cached)
  - Rate limiting (3–7s random delay between requests)
  - Session cookies (Screener requires a valid browser session)
  - Caching (avoids re-fetching data within the same session)
"""

import time
import random
import re
import json
import logging
from datetime import datetime
from urllib.robotparser import RobotFileParser
from typing import Optional
from functools import lru_cache

import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

BASE_URL = "https://www.screener.in"
ROBOTS_URL = f"{BASE_URL}/robots.txt"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": BASE_URL,
}

# Crawl-delay in seconds (min, max) – conservative to avoid Cloudflare bans
CRAWL_DELAY = (4, 8)


# ──────────────────────────────────────────────────────────────────────────────
# ScreenerScraper
# ──────────────────────────────────────────────────────────────────────────────

class ScreenerScraper:
    """
    Scrapes Screener.in for fundamental data and returns a metrics dict
    in the same format as GetFinanceValues (yfinance wrapper).

    Usage
    -----
        scraper = ScreenerScraper()
        metrics = scraper.GetFinanceValues("RELIANCE")
        # or for BSE code
        metrics = scraper.GetFinanceValues("500325", exchange="BSE")
    """

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update(HEADERS)
        self._robots: Optional[RobotFileParser] = None
        self._cache: dict = {}          # in-process cache keyed by ticker
        self._robots_loaded = False

    # ── robots.txt ────────────────────────────────────────────────────────────

    def _load_robots(self):
        if self._robots_loaded:
            return
        try:
            rp = RobotFileParser()
            rp.set_url(ROBOTS_URL)
            rp.read()
            self._robots = rp
            logger.info("robots.txt loaded from Screener.in")
        except Exception as e:
            logger.warning(f"Could not load robots.txt: {e}. Proceeding cautiously.")
            self._robots = None
        self._robots_loaded = True

    def _is_allowed(self, url: str) -> bool:
        self._load_robots()
        if self._robots is None:
            return True  # allow if we couldn't fetch robots.txt
        return self._robots.can_fetch("*", url)

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    def _polite_sleep(self):
        """Random delay to mimic human browsing and avoid rate-limiting."""
        delay = random.uniform(*CRAWL_DELAY)
        logger.debug(f"Sleeping {delay:.1f}s (polite crawl delay)")
        time.sleep(delay)

    def _fetch(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch a URL, respecting robots.txt and rate limits."""
        if not self._is_allowed(url):
            logger.warning(f"robots.txt disallows: {url}")
            return None

        self._polite_sleep()

        try:
            resp = self._session.get(url, timeout=15)
            if resp.status_code == 429:
                logger.warning("Rate limited (429). Sleeping 30s before retry.")
                time.sleep(30)
                resp = self._session.get(url, timeout=15)
            if resp.status_code == 403:
                logger.error("403 Forbidden – Cloudflare may be blocking. Try again later.")
                return None
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as e:
            logger.error(f"HTTP error fetching {url}: {e}")
            return None

    # ── URL builder ───────────────────────────────────────────────────────────

    def _build_url(self, ticker: str, consolidated: bool = True) -> str:
        variant = "consolidated" if consolidated else ""
        return f"{BASE_URL}/company/{ticker.upper()}/{variant}/"

    # ── Parsing helpers ───────────────────────────────────────────────────────

    def _parse_number(self, text: str) -> Optional[float]:
        """Convert Screener formatted strings to float using regex for robustness."""
        if not text:
            return None
        
        # Handle "High / Low" fields by taking the first part
        if "/" in text:
            text = text.split("/")[0].strip()

        # Handle negative in parentheses: (123) → -123
        if text.strip().startswith("(") and text.strip().endswith(")"):
            text = "-" + text.strip()[1:-1]

        # Extract only digits, dots, and optional leading minus
        match = re.search(r"-?\d+\.?\d*", text.replace(",", ""))
        if match:
            try:
                return float(match.group())
            except (ValueError, TypeError):
                return None
        return None

    def _extract_table(self, soup: BeautifulSoup, section_id: str) -> Optional[pd.DataFrame]:
        """
        Extract a data table from a Screener section (e.g. #profit-loss, #balance-sheet).
        Returns a DataFrame with years as columns and line items as the index.
        Columns are REVERSED to be latest-first for analysis logic.
        """
        section = soup.find("section", {"id": section_id})
        if not section:
            return None

        table = section.find("table")
        if not table:
            return None

        rows = table.find_all("tr")
        if not rows:
            return None

        # Header row → years
        header_cells = rows[0].find_all(["th", "td"])
        years = [c.get_text(strip=True) for c in header_cells[1:]]  # skip first "label" cell

        data = {}
        for row in rows[1:]:
            cells = row.find_all(["th", "td"])
            if not cells:
                continue
                
            # Clean label: "Sales +" -> "Sales"
            label = cells[0].get_text(strip=True).replace("+", "").strip()
            values = []
            for c in cells[1:]:
                num = self._parse_number(c.get_text(strip=True))
                values.append(num)
            if label:
                data[label] = values

        if not data:
            return None

        # Create DF: Index=Labels, Columns=Years
        df = pd.DataFrame(data, index=years).T  
        
        # REVERSE columns to be latest-first (latest year/TTM at index 0)
        df = df[df.columns[::-1]]
        
        return df

    def _get_series(self, df: Optional[pd.DataFrame], possible_names: list) -> Optional[pd.Series]:
        """Find a row in the parsed table by trying multiple possible label names."""
        if df is None or df.empty:
            return None
        for name in possible_names:
            # Exact
            if name in df.index:
                return df.loc[name].apply(pd.to_numeric, errors='coerce')
            # Fuzzy
            matches = [idx for idx in df.index if name.lower() in idx.lower()]
            if matches:
                return df.loc[matches[0]].apply(pd.to_numeric, errors='coerce')
        return None

    def _clean_num(self, val) -> any:
        if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
            return "N/A"
        try:
            return float(round(float(val), 2))
        except (TypeError, ValueError):
            return "N/A"

    def _calc_growth_cagr(self, series: Optional[pd.Series], periods: int) -> any:
        """CAGR over `periods` years. Series should be ordered latest-first."""
        if series is None or series.dropna().empty:
            return "N/A"
        s = series.dropna()
        p = min(periods, len(s) - 1)
        if p < 1:
            return "N/A"
        start_val = s.iloc[p]
        end_val = s.iloc[0]
        if start_val == 0 or start_val < 0 or end_val < 0:
            return "N/A"
        try:
            return round(((pow(end_val / start_val, 1 / p) - 1) * 100), 2)
        except Exception:
            return "N/A"

    def _calc_avg(self, series: Optional[pd.Series], periods: int) -> any:
        if series is None or series.empty:
            return "N/A"
        vals = series.iloc[:periods].dropna()
        return float(round(vals.mean(), 2)) if not vals.empty else "N/A"

    def _yoy_growth(self, series: Optional[pd.Series], idx0: int = 0, idx1: int = 1) -> any:
        """Simple YOY growth between two positions in the series."""
        if series is None or len(series.dropna()) <= idx1:
            return "N/A"
        s = series.dropna()
        v0, v1 = s.iloc[idx0], s.iloc[idx1]
        if v1 == 0:
            return "N/A"
        return self._clean_num(((v0 - v1) / abs(v1)) * 100)

    # ── Key Ratios extraction ─────────────────────────────────────────────────

    def _extract_key_ratios(self, soup: BeautifulSoup) -> dict:
        """
        Screener's #ratios section contains pre-computed ratios like
        Debt/Equity, ROE, ROCE, P/E, PEG, Market Cap etc. as a table.
        """
        ratios = {}
        section = soup.find("section", {"id": "ratios"})
        if not section:
            return ratios

        table = section.find("table")
        if not table:
            return ratios

        rows = table.find_all("tr")
        if not rows:
            return ratios

        # Header: years
        header_cells = rows[0].find_all(["th", "td"])
        years = [c.get_text(strip=True) for c in header_cells[1:]]

        for row in rows[1:]:
            cells = row.find_all(["th", "td"])
            if not cells:
                continue
            label = cells[0].get_text(strip=True)
            values = [self._parse_number(c.get_text(strip=True)) for c in cells[1:]]
            ratios[label] = dict(zip(years, values))

        return ratios

    def _extract_price_info(self, soup: BeautifulSoup) -> dict:
        """Extract current price, 52w high/low, market cap from the top section."""
        info = {}
        try:
            # Current price
            price_tag = soup.find("span", {"id": "current-price"}) or \
                        soup.find("span", {"class": re.compile(r"price")})
            if price_tag:
                info["currentPrice"] = self._parse_number(price_tag.get_text(strip=True))

            # Grab the top-level number list (High/Low/Market cap etc.)
            top_ratios = soup.find("ul", {"id": "top-ratios"})
            if top_ratios:
                for li in top_ratios.find_all("li"):
                    name_tag = li.find("span", {"class": "name"})
                    val_tag = li.find("span", {"class": "value"}) 
                    if name_tag and val_tag:
                        name = name_tag.get_text(strip=True).lower()
                        # Some values contain multiple numbers (High / Low)
                        num_tags = val_tag.find_all("span", {"class": "number"})
                        
                        if "high" in name and "low" in name:
                            # Split High / Low
                            if len(num_tags) >= 2:
                                info["fiftyTwoWeekHigh"] = self._parse_number(num_tags[0].get_text(strip=True))
                                info["fiftyTwoWeekLow"] = self._parse_number(num_tags[1].get_text(strip=True))
                            else:
                                raw_text = val_tag.get_text(strip=True)
                                if "/" in raw_text:
                                    parts = raw_text.split("/")
                                    info["fiftyTwoWeekHigh"] = self._parse_number(parts[0])
                                    info["fiftyTwoWeekLow"] = self._parse_number(parts[1])
                        
                        elif "market cap" in name or "mkt cap" in name:
                            info["marketCap"] = self._parse_number(val_tag.get_text(strip=True))
                        elif "current price" in name or "price" == name:
                            info["currentPrice"] = self._parse_number(val_tag.get_text(strip=True)) or info.get("currentPrice")
                        elif "roe" in name:
                            info["roe"] = self._parse_number(val_tag.get_text(strip=True))
                        elif "roce" in name:
                            info["roce"] = self._parse_number(val_tag.get_text(strip=True))
                        elif "p/e" in name or "pe" == name:
                            info["pe"] = self._parse_number(val_tag.get_text(strip=True))
                        elif "book value" in name:
                            info["bookValue"] = self._parse_number(val_tag.get_text(strip=True))
                        elif "dividend yield" in name:
                            info["dividendYield"] = self._parse_number(val_tag.get_text(strip=True))
        except Exception as e:
            logger.warning(f"Error parsing price info: {e}")
        return info

    def _extract_shareholding(self, soup: BeautifulSoup) -> dict:
        """Extract promoter holding from shareholding section."""
        sh = {}
        try:
            section = soup.find("section", {"id": "shareholding"})
            if not section:
                return sh
            table = section.find("table")
            if not table:
                return sh
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["th", "td"])
                if cells and "promoter" in cells[0].get_text(strip=True).lower():
                    # Take the most recent value (last non-empty column)
                    vals = [self._parse_number(c.get_text(strip=True)) for c in cells[1:]]
                    vals = [v for v in vals if v is not None]
                    if vals:
                        sh["promoterHolding"] = vals[-1]  # most recent quarter
        except Exception as e:
            logger.warning(f"Error parsing shareholding: {e}")
        return sh

    def _extract_quarterly_sales(self, soup: BeautifulSoup) -> Optional[pd.Series]:
        """Extract quarterly revenue series for YOY quarterly sales growth."""
        df = self._extract_table(soup, "quarters")
        if df is None:
            return None
        return self._get_series(df, ["Sales", "Revenue", "Total Revenue", "Net Sales"])

    def _compute_consistency_score(self, price_series: Optional[pd.Series]) -> dict:
        """45-degree log-linear regression on historical prices (same as yfinance wrapper)."""
        result = {"Consistency Score (R2)": "N/A", "45-Degree Trend": "N/A"}
        if price_series is None or len(price_series.dropna()) < 24:
            return result
        prices = price_series.dropna().values
        prices = prices[prices > 0]
        if len(prices) < 24:
            return result
        try:
            y_log = np.log(prices).reshape(-1, 1)
            x_time = np.arange(len(y_log)).reshape(-1, 1)
            model = LinearRegression().fit(x_time, y_log)
            r2 = round(model.score(x_time, y_log), 3)
            result["Consistency Score (R2)"] = r2
            result["45-Degree Trend"] = "Strong" if r2 > 0.85 else "Volatile/Cyclical"
        except Exception as e:
            logger.warning(f"Consistency score error: {e}")
        return result

    def _is_financial_institution(self, soup: BeautifulSoup, industry: str) -> bool:
        """Heuristic to detect if a company is a financial institution."""
        # Check industry
        financial_keywords = ["bank", "finance", "nbfc", "insurance", "fintech", "lending", "investment"]
        if industry and any(k in industry.lower() for k in financial_keywords):
            return True
        
        # Check about section
        about_tag = soup.find("div", {"class": "about"})
        if about_tag:
            about_text = about_tag.get_text(strip=True).lower()
            if any(k in about_text for k in financial_keywords):
                return True
                
        return False

    # ── Main public method ────────────────────────────────────────────────────

    def GetFinanceValues(self, ticker_name: str, exchange: str = "NSE", force_refresh: bool = False) -> dict:
        """
        Fetches fundamental data from Screener.in for an Indian stock.

        Parameters
        ----------
        ticker_name : str
            NSE symbol (e.g. 'RELIANCE') or BSE code (e.g. '500325').
            Strip .NS / .BO suffixes if present – this scraper handles exchange natively.
        exchange : str
            'NSE' (default) or 'BSE'. Only used as fallback if consolidated page fails.
        force_refresh : bool
            If True, bypass in-process cache and re-fetch.

        Returns
        -------
        dict
            Same keys as GetFinanceValues (yfinance wrapper).
        """
        # Clean ticker
        ticker_name = ticker_name.upper().replace(".NS", "").replace(".BO", "").replace(".BSE", "")

        cache_key = ticker_name
        if not force_refresh and cache_key in self._cache:
            logger.info(f"Returning cached data for {ticker_name}")
            return self._cache[cache_key]

        # Try consolidated first, then standalone
        soup = None
        is_consolidated = True
        for consolidated in [True, False]:
            url = self._build_url(ticker_name, consolidated=consolidated)
            logger.info(f"Fetching: {url}")
            soup = self._fetch(url)
            if soup and soup.find("section", {"id": "profit-loss"}):
                is_consolidated = consolidated
                break

        if soup is None:
            return {"error": f"Could not fetch data for {ticker_name} from Screener.in"}

        try:
            # ── Extract raw tables ────────────────────────────────────────
            pl_df = self._extract_table(soup, "profit-loss")     # P&L
            bs_df = self._extract_table(soup, "balance-sheet")   # Balance Sheet
            cf_df = self._extract_table(soup, "cash-flow")       # Cash Flow
            ratios_raw = self._extract_key_ratios(soup)          # Key Ratios table
            price_info = self._extract_price_info(soup)          # Price / Market data
            shareholding = self._extract_shareholding(soup)      # Promoter %
            q_rev_series = self._extract_quarterly_sales(soup)   # Quarterly sales

            # ── Series extraction ─────────────────────────────────────────
            # P&L
            rev = self._get_series(pl_df, ["Sales", "Revenue", "Net Sales", "Total Revenue"])
            net_inc = self._get_series(pl_df, ["Net Profit", "Profit after tax", "PAT", "Net Income"])
            op_inc = self._get_series(pl_df, ["Operating Profit", "EBIT", "PBDIT", "EBITDA"])
            int_exp = self._get_series(pl_df, ["Interest", "Finance Costs", "Interest Expense"])
            tax = self._get_series(pl_df, ["Tax", "Income Tax"])
            depreciation = self._get_series(pl_df, ["Depreciation", "D&A"])

            # Derive EBIT: Operating Profit or (Net Profit + Tax + Interest)
            ebit = op_inc
            if ebit is None and net_inc is not None and tax is not None and int_exp is not None:
                common = net_inc.index.intersection(tax.index).intersection(int_exp.index)
                if not common.empty:
                    ebit = net_inc[common] + tax[common] + int_exp[common]

            # Balance Sheet
            equity = self._get_series(bs_df, ["Shareholders' Funds", "Total Equity", "Net Worth", "Equity"])
            assets = self._get_series(bs_df, ["Total Assets", "Balance Sheet Total"])
            curr_assets = self._get_series(bs_df, ["Current Assets", "Total Current Assets"])
            curr_liab = self._get_series(bs_df, ["Current Liabilities", "Total Current Liabilities"])
            total_liab = self._get_series(bs_df, ["Total Liabilities", "Liabilities"])
            lt_debt = self._get_series(bs_df, ["Borrowings", "Long Term Borrowings", "Long-term Debt"])
            st_debt = self._get_series(bs_df, ["Short Term Borrowings", "Current Borrowings"])
            net_block = self._get_series(bs_df, ["Net Block", "Fixed Assets", "Net Fixed Assets", "Net PPE"])
            cwip = self._get_series(bs_df, ["Capital Work in Progress", "CWIP"])
            shares_out_series = self._get_series(bs_df, ["Equity Share Capital", "Share Capital"])

            # Debt: prefer Borrowings, fallback to LT+ST
            debt_series = self._get_series(bs_df, ["Total Debt", "Borrowings"])
            if debt_series is None:
                if lt_debt is not None and st_debt is not None:
                    common = lt_debt.index.intersection(st_debt.index)
                    debt_series = lt_debt[common].fillna(0) + st_debt[common].fillna(0)
                elif lt_debt is not None:
                    debt_series = lt_debt

            # Cash Flow
            ocf = self._get_series(cf_df, ["Cash from Operating Activity", "Operating Cash Flow", "Cash Flow from Operations"])
            capex = self._get_series(cf_df, ["Capital Expenditure", "Purchase of Fixed Assets", "Capex"])

            # OPM series from ratios or computed
            opm_series = None
            if "OPM %" in ratios_raw:
                opm_series = pd.Series(ratios_raw["OPM %"]).dropna()
            elif op_inc is not None and rev is not None:
                common = op_inc.index.intersection(rev.index)
                if not common.empty:
                    opm_series = (op_inc[common] / rev[common].replace(0, np.nan)) * 100

            # ROE series from ratios or computed
            roe_series = None
            if "Return on equity %" in ratios_raw or "ROE %" in ratios_raw:
                key = "Return on equity %" if "Return on equity %" in ratios_raw else "ROE %"
                roe_series = pd.Series(ratios_raw[key]).dropna()
            elif net_inc is not None and equity is not None:
                common = net_inc.index.intersection(equity.index)
                if not common.empty:
                    roe_series = (net_inc[common] / equity[common].replace(0, np.nan)) * 100

            # ROCE series
            roce_series = None
            if "ROCE %" in ratios_raw:
                roce_series = pd.Series(ratios_raw["ROCE %"]).dropna()
            elif ebit is not None and assets is not None and curr_liab is not None:
                try:
                    aligned_assets = assets.reindex(ebit.index, method='nearest')
                    aligned_liab = curr_liab.reindex(ebit.index, method='nearest')
                    cap_employed = aligned_assets - aligned_liab
                    roce_series = (ebit / cap_employed.replace(0, np.nan)) * 100
                except Exception:
                    roce_series = None

            # Shares outstanding (from balance sheet equity capital or price info)
            shares_out = None
            if shares_out_series is not None and not shares_out_series.empty:
                # Screener stores share capital in Cr; divide by face value assumed ₹1–₹10
                # This is tricky; use as proxy only for NCAVPS
                shares_out = shares_out_series.iloc[0]

            # Consistency score (no price history from Screener, mark N/A)
            # You can combine with yfinance price history for this specific metric
            trend_data = {"Consistency Score (R2)": "N/A (use yfinance for price history)", "45-Degree Trend": "N/A"}

            # ── Build metrics dict (same keys as yfinance wrapper) ────────
            metrics: dict = {
                "Data Type": "Consolidated" if is_consolidated else "Standalone",
                **trend_data,
            }

            # 1. Sales & Profit Growth
            metrics["Sales growth (Current/Last Year)"] = self._yoy_growth(rev)
            metrics["Profit growth (Current/Last Year)"] = self._yoy_growth(net_inc)
            for y in [3, 5, 7, 10]:
                metrics[f"Sales growth {y}Years"] = self._calc_growth_cagr(rev, y)
                metrics[f"Profit growth {y}Years"] = self._calc_growth_cagr(net_inc, y)

            # 2. OPM
            metrics["OPM (Operating Profit Margin - Current)"] = (
                self._clean_num(opm_series.iloc[0]) if opm_series is not None and not opm_series.empty else "N/A"
            )
            metrics["OPM last year"] = (
                self._clean_num(opm_series.iloc[1]) if opm_series is not None and len(opm_series) > 1 else "N/A"
            )
            metrics["OPM 5Year"] = self._calc_avg(opm_series, 5)
            metrics["OPM 10Year"] = self._calc_avg(opm_series, 10)

            # 3. ROE
            metrics["Return on equity (Current)"] = (
                self._clean_num(roe_series.iloc[0]) if roe_series is not None and not roe_series.empty else "N/A"
            )
            metrics["Return on equity preceding year"] = (
                self._clean_num(roe_series.iloc[1]) if roe_series is not None and len(roe_series) > 1 else "N/A"
            )
            for y in [3, 5, 7, 10]:
                metrics[f"Average return on equity {y}Years"] = self._calc_avg(roe_series, y)

            # 4. ROCE
            metrics["Return on capital employed (Current ROCE)"] = (
                self._clean_num(roce_series.iloc[0]) if roce_series is not None and not roce_series.empty else "N/A"
            )
            for y in [3, 5, 7, 10]:
                metrics[f"Average return on capital employed {y}Years"] = self._calc_avg(roce_series, y)

            # 5. Solvency
            if debt_series is not None and equity is not None:
                try:
                    aligned_debt = debt_series.reindex(equity.index, method='nearest')
                    de_series = aligned_debt / equity.replace(0, np.nan)
                    metrics["Debt to equity"] = self._clean_num(de_series.iloc[0])
                except Exception:
                    metrics["Debt to equity"] = "N/A"
            else:
                metrics["Debt to equity"] = "N/A"

            if ebit is not None and int_exp is not None:
                try:
                    common = ebit.index.intersection(int_exp.index)
                    if not common.empty and int_exp[common].iloc[0] != 0:
                        metrics["Interest Coverage Ratio"] = self._clean_num(
                            ebit[common].iloc[0] / abs(int_exp[common].iloc[0])
                        )
                    else:
                        metrics["Interest Coverage Ratio"] = "N/A"
                except Exception:
                    metrics["Interest Coverage Ratio"] = "N/A"
            else:
                metrics["Interest Coverage Ratio"] = "N/A"

            # 6. Cash Flow
            metrics["Operating cash flow 5years"] = (
                self._clean_num(ocf.iloc[:5].dropna().sum()) if ocf is not None and not ocf.empty else "N/A"
            )
            metrics["Average EBIT 5Year"] = self._calc_avg(ebit, 5)
            metrics["Cash from operations last year"] = (
                self._clean_num(ocf.iloc[0]) if ocf is not None and not ocf.empty else "N/A"
            )

            # 7. 52-week high / low
            curr_price = price_info.get("currentPrice")
            low_52w = price_info.get("fiftyTwoWeekLow")
            high_52w = price_info.get("fiftyTwoWeekHigh")
            metrics["Up from 52w low"] = (
                round(((curr_price - low_52w) / low_52w * 100), 2) if curr_price and low_52w else "N/A"
            )
            metrics["Down from 52w high"] = (
                round(((high_52w - curr_price) / high_52w * 100), 2) if curr_price and high_52w else "N/A"
            )

            # 8. Net Block & CWIP
            metrics["Net block (Current)"] = (
                self._clean_num(net_block.iloc[0]) if net_block is not None and not net_block.empty else "N/A"
            )
            metrics["Net block (Preceding Year)"] = (
                self._clean_num(net_block.iloc[1]) if net_block is not None and len(net_block) > 1 else "N/A"
            )
            metrics["Capital work in progress (Current)"] = (
                self._clean_num(cwip.iloc[0]) if cwip is not None and not cwip.empty else "N/A"
            )
            metrics["Capital work in progress (Preceding Year)"] = (
                self._clean_num(cwip.iloc[1]) if cwip is not None and len(cwip) > 1 else "N/A"
            )

            # 9. Market & Ownership
            metrics["Market Capitalization"] = price_info.get("marketCap", "N/A")
            metrics["Promoter holding"] = shareholding.get("promoterHolding", "N/A")
            
            # Pledged percentage - from top ratios or Peer section often
            metrics["Pledged percentage"] = price_info.get("pledged", "N/A")
            if metrics["Pledged percentage"] == "N/A":
                 # Try ratios table if present
                 for r_name in ratios_raw:
                     if "pledged" in r_name.lower():
                         metrics["Pledged percentage"] = list(ratios_raw[r_name].values())[-1]
                         break

            # --- Missing Price/Ratio Info (Crucial for UI) ---
            metrics["currentPrice"] = price_info.get("currentPrice", "N/A")
            metrics["fiftyTwoWeekHigh"] = price_info.get("fiftyTwoWeekHigh", "N/A")
            metrics["fiftyTwoWeekLow"] = price_info.get("fiftyTwoWeekLow", "N/A")
            metrics["bookValue"] = price_info.get("bookValue", "N/A")
            metrics["dividendYield"] = price_info.get("dividendYield", "N/A")
            metrics["trailingPE"] = price_info.get("pe", "N/A") # Map to trailingPE
            metrics["roe"] = price_info.get("roe", "N/A")
            metrics["roce"] = price_info.get("roce", "N/A")

            # Industry & Financial Detection
            industry = price_info.get("industry", "")
            if not industry:
                peer_section = soup.find("section", {"id": "peers"})
                if peer_section:
                    ind_link = peer_section.find("a", href=re.compile(r"/company/industry/"))
                    if ind_link:
                        industry = ind_link.get_text(strip=True)
            
            metrics["Industry"] = industry
            metrics["isFinancial"] = self._is_financial_institution(soup, industry)

            # 10. YOY Quarterly Sales Growth (last 5 quarters, most recent vs same quarter last year)
            if q_rev_series is not None and len(q_rev_series.dropna()) >= 5:
                q = q_rev_series.dropna()
                metrics["YOY Quarterly sales growth"] = self._yoy_growth(q, idx0=0, idx1=4)
            else:
                metrics["YOY Quarterly sales growth"] = "N/A"

            # 11. Financial Leverage
            if assets is not None and equity is not None:
                try:
                    common = assets.index.intersection(equity.index)
                    if not common.empty:
                        fl = assets[common] / equity[common].replace(0, np.nan)
                        metrics["Financial leverage"] = self._clean_num(fl.iloc[0])
                    else:
                        metrics["Financial leverage"] = "N/A"
                except Exception:
                    metrics["Financial leverage"] = "N/A"
            else:
                metrics["Financial leverage"] = "N/A"

            # 12. Return on Assets
            if net_inc is not None and assets is not None:
                try:
                    common = net_inc.index.intersection(assets.index)
                    if not common.empty:
                        roa = (net_inc[common] / assets[common].replace(0, np.nan)) * 100
                        metrics["Return on assets"] = self._clean_num(roa.iloc[0])
                    else:
                        metrics["Return on assets"] = "N/A"
                except Exception:
                    metrics["Return on assets"] = "N/A"
            else:
                metrics["Return on assets"] = "N/A"

            # 13. Interest Last Year
            metrics["Interest last year"] = (
                self._clean_num(int_exp.iloc[1]) if int_exp is not None and len(int_exp.dropna()) > 1 else "N/A"
            )

            # 14. NCAVPS
            if curr_assets is not None and total_liab is not None and shares_out:
                try:
                    common = curr_assets.index.intersection(total_liab.index)
                    if not common.empty:
                        ncav = curr_assets[common].iloc[0] - total_liab[common].iloc[0]
                        # shares_out from Screener is in Cr units of face value — this is approximate
                        metrics["NCAVPS"] = self._clean_num(ncav / shares_out) if shares_out else "N/A"
                    else:
                        metrics["NCAVPS"] = "N/A"
                except Exception:
                    metrics["NCAVPS"] = "N/A"
            else:
                metrics["NCAVPS"] = "N/A"

            # 15. PEG Ratio
            # PEG = P/E / Earnings Growth Rate (5yr)
            pe = price_info.get("pe")
            earnings_growth = metrics.get("Profit growth 5Years")
            if pe and earnings_growth != "N/A" and earnings_growth and earnings_growth > 0:
                metrics["PEG Ratio"] = self._clean_num(pe / earnings_growth)
            else:
                # Try from ratios table
                peg_key = next((k for k in ratios_raw if "peg" in k.lower()), None)
                metrics["PEG Ratio"] = (
                    list(ratios_raw[peg_key].values())[-1] if peg_key else "N/A"
                )

            # 16. Dividend Payout Ratio
            div_payout = self._get_series(pl_df, ["Dividend Payout %", "Dividend Payout Ratio"])
            if div_payout is not None and not div_payout.empty:
                metrics["Dividend Payout Ratio"] = self._clean_num(div_payout.iloc[0])
            else:
                metrics["Dividend Payout Ratio"] = "N/A"

            # Cache result
            self._cache[cache_key] = metrics
            return metrics

        except Exception as e:
            logger.exception(f"Error processing Screener data for {ticker_name}: {e}")
            return {"error": str(e)}