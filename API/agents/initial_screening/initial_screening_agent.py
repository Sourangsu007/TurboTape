import json
from pathlib import Path
from llm.llm import get_llm_instance

class InitialScreeningAgent:
    """
    Agent responsible for the initial screening of stocks.
    """
    def __init__(self):
        self.llm = get_llm_instance()
        self.ticker_prompt_path = Path(__file__).parent / "initial_prompt.md"
        self.validate_prompt_path = Path(__file__).parent / "Validate_Params.md"

    def execute(self, stock_name: str):
        """
        Executes the initial screening: resolves ticker, fetches data, and validates parameters.
        """
        # Step 1: Resolve Ticker Name
        if not self.ticker_prompt_path.exists():
            raise FileNotFoundError(f"Ticker prompt file not found at {self.ticker_prompt_path}")
            
        with open(self.ticker_prompt_path, "r") as f:
            ticker_template = f.read()
            
        ticker_prompt = ticker_template.replace("{{stock_name}}", stock_name)
        
        ticker_response = self.llm.completion(
            messages=[{"role": "user", "content": ticker_prompt}],
            response_format={"type": "json_object"}
        )
        
        try:
            ticker_result = json.loads(ticker_response.choices[0].message.content)
            ticker_name = ticker_result.get("tickerName", "").strip()
            industry = ticker_result.get("industry", "Unknown")
            is_financial = ticker_result.get("isFinancial", False)
            print(f"Found Ticker Name: {ticker_name}")
            if not ticker_name:
                return {
                    "success": False,
                    "financial_data": "",
                    "result_1": "fail",
                    "reason_1": "Could not resolve ticker name from LLM",
                    "result_2": "fail",
                    "reason_2": "",
                    "ticker_name": ticker_name
                }
            
            # Step 2: Fetch Financial Data (Layer 2 Cache Check)
            from caching.cache_manager import cache_manager
            raw_cache_key = cache_manager.get_raw_data_key(ticker_name)
            financial_data = cache_manager.get(raw_cache_key)
            
            if financial_data:
                print(f"Layer 2 Cache Hit (Raw): {raw_cache_key}")
            else:
                from agents.initial_screening.yfinance_helper import YFinanceHelper
                financial_data = YFinanceHelper.GetFinanceValues(ticker_name)
                
                is_fetch_error = not financial_data or "error" in financial_data
                if is_fetch_error:
                    error_msg = financial_data.get('error') if isinstance(financial_data, dict) else 'Unknown error'
                    financial_data = {"error": error_msg, "Data Status": "yfinance completely failed, trying Screener.in"}
                    missing_count = 999  # Force fallback
                else:
                    missing_count = list(financial_data.values()).count("N/A")

                # Step 2.1: Screener.in Fallback
                if missing_count > 3:
                    try:
                        from agents.initial_screening.Screener_Scrapper import ScreenerScraper
                        scraper = ScreenerScraper()
                        screener_data = scraper.GetFinanceValues(ticker_name)
                        
                        if screener_data and "error" not in screener_data:
                            print(f"Screener data fetched for {stock_name}. Merging...")
                            merged_data = financial_data.copy()
                            for key, value in screener_data.items():
                                if value != "N/A":
                                    merged_data[key] = value
                            
                            financial_data = merged_data
                            missing_count = list(financial_data.values()).count("N/A")
                            print(f"New missing count after Screener: {missing_count}")
                    except Exception as e:
                        print(f"Screener scraping failed for {stock_name}: {e}")

                # Step 2.5: LLM Data Fallback Mechanism
                if missing_count > 3:
                    fallback_prompt_path = Path(__file__).parent / "fallback.md"
                    if fallback_prompt_path.exists():
                        with open(fallback_prompt_path, "r") as f:
                            fallback_template = f.read()
                            
                        fallback_prompt = fallback_template.replace("[INSERT STOCK NAME]", stock_name)
                        fallback_prompt = fallback_prompt.replace("[INSERT PARTIAL DICTIONARY/JSON HERE]", json.dumps(financial_data, indent=2))
                        
                        try:
                            fallback_response = self.llm.completion(
                                messages=[{"role": "user", "content": fallback_prompt}],
                                response_format={"type": "json_object"}
                            )
                            fallback_result = json.loads(fallback_response.choices[0].message.content)
                            
                            if is_fetch_error:
                                financial_data = fallback_result
                            else:
                                for key, value in fallback_result.items():
                                    if key in financial_data:
                                        financial_data[key] = value
                        except Exception as e:
                            print(f"Fallback LLM failed for {stock_name}: {e}")
                            if is_fetch_error:
                                return {
                                    "success": False,
                                    "financial_data": financial_data,
                                    "result_1": "fail",
                                    "reason_1": f"Error fetching financial data from yfinance, and fallback LLM failed: {e}",
                                    "result_2": "fail",
                                    "reason_2": "",
                                    "ticker_name": ticker_name  
                                }

                # Cache the successfully fetched/merged data
                if financial_data and "error" not in financial_data:
                    cache_manager.set(raw_cache_key, financial_data, expire=cache_manager.expire_data)

            # Step 3: Validate Parameters
            if is_financial:
                self.validate_prompt_path = Path(__file__).parent / "Initial_screening_financial.md"
            else:
                self.validate_prompt_path = Path(__file__).parent / "initial_screening.md"
                
            if not self.validate_prompt_path.exists():
                raise FileNotFoundError(f"Validation prompt file not found at {self.validate_prompt_path}")
                
            with open(self.validate_prompt_path, "r") as f:
                validate_template = f.read()
                
            validate_prompt = validate_template.replace("{{stock_name}}", stock_name)
            validate_prompt = validate_prompt.replace("{{industry}}", industry)
            validate_prompt = validate_prompt.replace("{{is_financial}}", "Yes" if is_financial else "No")
            validate_prompt = validate_prompt.replace("{{financial_data}}", json.dumps(financial_data, indent=2))
            
            validate_response = self.llm.completion(
                messages=[{"role": "user", "content": validate_prompt}],
                response_format={"type": "json_object"}
            )
            
            try:
                validation_result = json.loads(validate_response.choices[0].message.content)
                
                return {
                    "success": True,
                    "financial_data": financial_data,
                    "industry": industry,
                    "is_financial": is_financial,
                    "result_1": validation_result.get("result_1", "fail"),
                    "reason_1": validation_result.get("reason_1", ""),
                    "result_2": validation_result.get("result_2", "fail"),
                    "reason_2": validation_result.get("reason_2", ""),
                    "ticker_name": ticker_name
                }
                
            except json.JSONDecodeError:
                return {
                    "success": False,
                    "financial_data": financial_data,
                    "result_1": "fail",
                    "reason_1": "LLM failed to return valid JSON for validation step",
                    "result_2": "fail",
                    "reason_2": "",
                    "ticker_name": ""
                }

        except json.JSONDecodeError:
            return {
                "success": False,
                "financial_data": "",
                "result_1": "fail",
                "reason_1": "LLM failed to return valid JSON for ticker resolution step",
                "result_2": "fail",
                "reason_2": "",
                "ticker_name": ""
            }
