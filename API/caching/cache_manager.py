import os
import diskcache
from dotenv import load_dotenv

load_dotenv()

class CacheManager:
    """
    Manages disk-based caching for the TradingApp API using diskcache.
    Provides two layers of caching:
    1. Full API response caching (stockName_Core)
    2. Data-level caching (Raw financials and Technical indicators)
    """
    def __init__(self):
        # Cache directory in the API root
        current_dir = os.path.dirname(os.path.abspath(__file__))
        cache_dir = os.path.join(os.path.dirname(current_dir), "cache_data")
        self.cache = diskcache.Cache(cache_dir)
        
        # TTL settings from environment (defaults provided)
        self.expire_core = int(os.getenv("CACHE_EXPIRE_CORE_SECONDS", "3600"))
        self.expire_data = int(os.getenv("CACHE_EXPIRE_DATA_SECONDS", "86400"))

    def get(self, key):
        return self.cache.get(key)

    def set(self, key, value, expire=None):
        self.cache.set(key, value, expire=expire)

    def delete(self, key):
        self.cache.delete(key)

    def get_analysis_key(self, stock_name, portfolio_type):
        return f"{stock_name.upper()}_{portfolio_type.upper()}"

    def get_raw_data_key(self, ticker):
        return f"{ticker.upper()}_raw"

    def get_tech_data_key(self, ticker):
        return f"{ticker.upper()}_tech"

# Global instance
cache_manager = CacheManager()
