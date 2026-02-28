import yfinance as yf
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression

class YFinanceHelper:
    """
    Helper class to fetch financial data using the yfinance library.
    """
    
    @staticmethod
    def GetFinanceValues(ticker_name: str):
        """
        Fetches and calculates detailed stock information, including 10-year consistency (45-degree) score.
        """
        try:
            # Standardize for NSE if not specified
            if not (ticker_name.endswith(".NS") or ticker_name.endswith(".BO") or ticker_name.endswith(".BSE")):
                if not "." in ticker_name:
                    ticker_name = f"{ticker_name}.NS"
                
            ticker = yf.Ticker(ticker_name)
            
            # 1. Fetch Price History for 10-Year Consistency Check (45-Degree Check)
            hist = ticker.history(period="10y", interval="1mo", auto_adjust=True)
            trend_data = {"Consistency Score (R2)": "N/A", "45-Degree Trend": "N/A"}
            
            if not hist.empty and len(hist) > 24:
                prices = hist['Close'].dropna().values
                valid_idx = prices > 0
                prices = prices[valid_idx]
                
                if len(prices) > 24:
                    y_log = np.log(prices).reshape(-1, 1)
                    x_time = np.arange(len(y_log)).reshape(-1, 1)
                    model = LinearRegression().fit(x_time, y_log)
                    r_squared = model.score(x_time, y_log)
                    trend_data["Consistency Score (R2)"] = round(r_squared, 3)
                    trend_data["45-Degree Trend"] = "Strong" if r_squared > 0.85 else "Volatile/Cyclical"

            # 2. Fetch Financial Data Sources
            income_stmt = ticker.financials
            balance_sheet = ticker.balance_sheet
            cash_flow = ticker.cashflow
            info = ticker.info
            
            if income_stmt.empty or balance_sheet.empty:
                return {"error": "Financial statements not found"}

            # Check for Consolidated Data
            is_cons = any("Consolidated" in str(col) for col in income_stmt.columns)

            # --- Helper Functions ---
            def get_row(df, possible_names):
                if df is None or df.empty: return None
                # First try exact match
                for name in possible_names:
                    if name in df.index: return df.loc[name]
                # Then try fuzzy match
                for name in possible_names:
                    matches = [idx for idx in df.index if name.lower() in idx.lower()]
                    if matches: return df.loc[matches[0]]
                return None

            def clean_num(val):
                if val is None or pd.isna(val) or (isinstance(val, (float, int, np.number)) and (np.isnan(val) or np.isinf(val))):
                    return "N/A"
                return float(round(val, 2))

            def calc_growth_cagr(series, periods):
                if series is None or len(series) < 2: return "N/A"
                p = min(periods, len(series) - 1)
                start_val = series.iloc[p]
                end_val = series.iloc[0]
                if pd.isna(start_val) or pd.isna(end_val) or start_val == 0: return "N/A"
                if start_val < 0 or end_val < 0: return "N/A"
                return round(((pow(end_val / start_val, 1/p) - 1) * 100), 2)

            def calc_avg(series, periods):
                if series is None or series.empty: return "N/A"
                p = min(periods, len(series))
                vals = series.iloc[:p].dropna()
                return float(round(vals.mean(), 2)) if not vals.empty else "N/A"

            # 3. Data Extraction
            rev = get_row(income_stmt, ["Total Revenue", "Operating Revenue", "Revenue"])
            net_inc = get_row(income_stmt, ["Net Income", "Net Income Common Stockholders"])
            ebit = get_row(income_stmt, ["EBIT", "Operating Income", "Operating Income / Expense"])
            op_inc = get_row(income_stmt, ["Operating Income"])
            int_exp = get_row(income_stmt, ["Interest Expense", "Interest Expense Non-Operating", "Interest Income Expense"])
            
            equity = get_row(balance_sheet, ["Stockholders Equity", "Total Equity", "Common Stock Equity", "Total Stockholders Equity"])
            assets = get_row(balance_sheet, ["Total Assets"])
            curr_liab = get_row(balance_sheet, ["Total Current Liabilities", "Current Liabilities"])
            
            debt = get_row(balance_sheet, ["Total Debt"])
            if debt is None:
                lt_debt = get_row(balance_sheet, ["Long Term Debt"])
                st_debt = get_row(balance_sheet, ["Current Debt", "Short Long Term Debt"])
                if lt_debt is not None:
                    debt = lt_debt.fillna(0) + (st_debt.fillna(0) if st_debt is not None else 0)
            if debt is not None:
                debt_series = debt
            elif lt_debt is not None or st_debt is not None:
                # Sum them up, treating NaNs as 0
                debt_series = lt_debt.fillna(0) + st_debt.fillna(0)
            else:
                debt_series = None
            net_block = get_row(balance_sheet, ["Net PPE", "Properties", "Property Plant Equipment Net", "Net Property Plant Equipment"])
            cwip = get_row(balance_sheet, ["Construction In Progress", "Capital Work In Progress"])
            ocf = get_row(cash_flow, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities", "Total Cash From Operating Activities"])

            # 4. Metrics Calculation
            metrics = {
                "Data Type": "Consolidated" if is_cons else "Standalone",
                **trend_data
            }

            # 1. Growth Metrics
            if rev is not None and len(rev) > 1 and not pd.isna(rev.iloc[1]) and rev.iloc[1] != 0:
                metrics["Sales growth (Current/Last Year)"] = clean_num(((rev.iloc[0] - rev.iloc[1]) / abs(rev.iloc[1])) * 100)
            else:
                metrics["Sales growth (Current/Last Year)"] = "N/A"
                
            if net_inc is not None and len(net_inc) > 1 and not pd.isna(net_inc.iloc[1]) and net_inc.iloc[1] != 0:
                metrics["Profit growth (Current/Last Year)"] = clean_num(((net_inc.iloc[0] - net_inc.iloc[1]) / abs(net_inc.iloc[1])) * 100)
            else:
                metrics["Profit growth (Current/Last Year)"] = "N/A"
            
            for y in [3, 5, 7, 10]:
                metrics[f"Sales growth {y}Years"] = calc_growth_cagr(rev, y)
                metrics[f"Profit growth {y}Years"] = calc_growth_cagr(net_inc, y)

            # 2. Profitability & Efficiency
            opm_series = None
            if op_inc is not None and rev is not None:
                common_idx = op_inc.index.intersection(rev.index)
                if not common_idx.empty:
                    opm_series = (op_inc.loc[common_idx] / rev.loc[common_idx] * 100)

            metrics["OPM (Operating Profit Margin - Current)"] = clean_num(opm_series.iloc[0]) if opm_series is not None and not opm_series.empty else "N/A"
            metrics["OPM last year"] = clean_num(opm_series.iloc[1]) if opm_series is not None and len(opm_series) > 1 else "N/A"
            metrics["OPM 5Year"] = calc_avg(opm_series, 5)
            metrics["OPM 10Year"] = calc_avg(opm_series, 10)

            roe_series = None
            if net_inc is not None and equity is not None:
                common_idx = net_inc.index.intersection(equity.index)
                if not common_idx.empty:
                    roe_series = (net_inc.loc[common_idx] / equity.loc[common_idx] * 100)

            metrics["Return on equity (Current)"] = clean_num(roe_series.iloc[0]) if roe_series is not None and not roe_series.empty else "N/A"
            for y in [3, 5, 7, 10]:
                metrics[f"Average return on equity {y}Years"] = calc_avg(roe_series, y)

            roce_series = None
            if ebit is not None and assets is not None and curr_liab is not None:
                        # 1. Align all data to the EBIT dates to avoid intersection empty-sets
                        # This maps the closest Balance Sheet date to the Income Statement date
                        try:
                            # Reindexing ensures we have the same dates across all three series
                            aligned_assets = assets.reindex(ebit.index, method='nearest')
                            aligned_liab = curr_liab.reindex(ebit.index, method='nearest')
        
                            cap_employed = aligned_assets - aligned_liab
        
                            # Avoid division by zero
                            roce_series = (ebit / cap_employed.replace(0, np.nan)) * 100
                        except Exception:
                            roce_series = None

            # Now your existing metrics assignment will work
            metrics["Return on capital employed (Current ROCE)"] = clean_num(roce_series.iloc[0]) if roce_series is not None and not roce_series.empty else "N/A"
            for y in [3, 5, 7, 10]:
                metrics[f"Average return on capital employed {y}Years"] = calc_avg(roce_series, y)

            # 3. Solvency & Cash Flow
            common_solv_idx = equity.index.intersection(debt.index) if equity is not None and debt is not None else None
            if debt_series is not None and equity is not None:
                # Reindex debt to match equity dates to handle minor date mismatches
                aligned_debt = debt_series.reindex(equity.index, method='nearest')
                
                # Calculate series
                d_e_series = aligned_debt / equity.replace(0, np.nan)
    
                metrics["Debt to equity"] = clean_num(d_e_series.iloc[0])
            else:
                # Last ditch effort: Try the 'info' dictionary which often has a pre-calc'd ratio
                d_e_info = info.get('debtToEquity')
                metrics["Debt to equity"] = clean_num(d_e_info / 100) if d_e_info else "N/A"
            
            common_int_idx = ebit.index.intersection(int_exp.index) if ebit is not None and int_exp is not None else None
            metrics["Interest Coverage Ratio"] = clean_num(ebit.loc[common_int_idx].iloc[0] / abs(int_exp.loc[common_int_idx].iloc[0])) if common_int_idx is not None and not common_int_idx.empty and int_exp.loc[common_int_idx].iloc[0] != 0 else "N/A"
            
            metrics["Operating cash flow 5years"] = clean_num(ocf.iloc[:5].dropna().sum()) if ocf is not None and not ocf.empty else "N/A"
            metrics["Average EBIT 5Year"] = calc_avg(ebit, 5)
            metrics["Cash from operations last year"] = clean_num(ocf.iloc[0]) if ocf is not None and not ocf.empty else "N/A"

            # 4. Market Price & Capital Expenditure
            curr_price = info.get('regularMarketPrice') or info.get('currentPrice')
            low_52w = info.get('fiftyTwoWeekLow')
            high_52w = info.get('fiftyTwoWeekHigh')
            
            metrics["Up from 52w low"] = round(((curr_price - low_52w) / low_52w * 100), 2) if curr_price and low_52w else "N/A"
            metrics["Down from 52w high"] = round(((high_52w - curr_price) / high_52w * 100), 2) if curr_price and high_52w else "N/A"
            
            metrics["Net block (Current)"] = clean_num(net_block.iloc[0]) if net_block is not None and not net_block.empty else "N/A"
            metrics["Net block (Preceding Year)"] = clean_num(net_block.iloc[1]) if net_block is not None and len(net_block) > 1 else "N/A"
            metrics["Capital work in progress (Current)"] = clean_num(cwip.iloc[0]) if cwip is not None and not cwip.empty else "N/A"
            metrics["Capital work in progress (Preceding Year)"] = clean_num(cwip.iloc[1]) if cwip is not None and len(cwip) > 1 else "N/A"

            # 5. Ownership & Size
            metrics["Market Capitalization"] = info.get('marketCap', "N/A")
            metrics["Promoter holding"] = info.get('heldPercentInsiders', "N/A")
            # 6. Additional Financial Sector Metrics
            # YOY Quarterly sales growth
            quarterly_income = ticker.quarterly_financials
            q_rev = get_row(quarterly_income, ["Total Revenue", "Operating Revenue", "Revenue"])
            if q_rev is not None and len(q_rev) >= 5 and not pd.isna(q_rev.iloc[4]) and q_rev.iloc[4] != 0:
                metrics["YOY Quarterly sales growth"] = clean_num(((q_rev.iloc[0] - q_rev.iloc[4]) / abs(q_rev.iloc[4])) * 100)
            else:
                metrics["YOY Quarterly sales growth"] = info.get('revenueGrowth', "N/A")
                if metrics["YOY Quarterly sales growth"] != "N/A":
                    metrics["YOY Quarterly sales growth"] = clean_num(metrics["YOY Quarterly sales growth"] * 100)

            # Interest last year
            metrics["Interest last year"] = clean_num(int_exp.iloc[1]) if int_exp is not None and len(int_exp) > 1 else "N/A"

            # Financial leverage (Total Assets / Total Equity)
            if assets is not None and equity is not None:
                common_lev_idx = assets.index.intersection(equity.index)
                if not common_lev_idx.empty:
                    fin_lev_series = assets.loc[common_lev_idx] / equity.loc[common_lev_idx].replace(0, np.nan)
                    metrics["Financial leverage"] = clean_num(fin_lev_series.iloc[0])
                else:
                    metrics["Financial leverage"] = "N/A"
            else:
                 metrics["Financial leverage"] = "N/A"

            # Return on assets
            metrics["Return on assets"] = clean_num(info.get('returnOnAssets', 0) * 100) if info.get('returnOnAssets') is not None else "N/A"
            if metrics["Return on assets"] == "N/A" and net_inc is not None and assets is not None:
                 common_roa_idx = net_inc.index.intersection(assets.index)
                 if not common_roa_idx.empty:
                     roa_series = (net_inc.loc[common_roa_idx] / assets.loc[common_roa_idx].replace(0, np.nan) * 100)
                     metrics["Return on assets"] = clean_num(roa_series.iloc[0])

            # Return on equity preceding year
            metrics["Return on equity preceding year"] = clean_num(roe_series.iloc[1]) if roe_series is not None and len(roe_series) > 1 else "N/A"

            # NCAVPS (Net Current Asset Value Per Share) = (Current Assets - Total Liabilities) / Shares Outstanding
            curr_assets = get_row(balance_sheet, ["Total Current Assets", "Current Assets"])
            total_liab = get_row(balance_sheet, ["Total Liabilities Net Minority Interest", "Total Liabilities"])
            shares_out = info.get('sharesOutstanding')
            
            if curr_assets is not None and total_liab is not None and shares_out:
                common_ncavps_idx = curr_assets.index.intersection(total_liab.index)
                if not common_ncavps_idx.empty:
                    ncav = curr_assets.loc[common_ncavps_idx].iloc[0] - total_liab.loc[common_ncavps_idx].iloc[0]
                    metrics["NCAVPS"] = clean_num(ncav / shares_out)
                else:
                    metrics["NCAVPS"] = "N/A"
            else:
                metrics["NCAVPS"] = "N/A"

            # PEG Ratio
            metrics["PEG Ratio"] = info.get('pegRatio', "N/A")

            # Dividend Payout Ratio
            metrics["Dividend Payout Ratio"] = clean_num(info.get('payoutRatio', 0) * 100) if info.get('payoutRatio') is not None else "N/A"

            return metrics

        except Exception as e:
            print(f"Error fetching data from yfinance for {ticker_name}: {e}")
            return {"error": str(e)}
            
