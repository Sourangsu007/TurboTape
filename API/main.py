from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from orchestrator.agent_orchestrator import AgentOrchestrator
from schemas.schemas import AnalyzeStock, BatchAnalysisRequest
from caching.cache_manager import cache_manager
from util.util import FileUtil

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

orchestrator = AgentOrchestrator()

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.post("/analyze/{stockname}")
async def analyze_stock(stockname: str, body: AnalyzeStock):
    cache_key = cache_manager.get_analysis_key(stockname, body.portfolio_type)
    cached_res = cache_manager.get(cache_key)
    if cached_res:
        print(f"Layer 1 Cache Hit: {cache_key}")
        return cached_res
        
    result = orchestrator.execute(stockname, body)
    
    if result.get("success"):
        cache_manager.set(cache_key, result, expire=cache_manager.expire_core)
        
    return result

@app.post("/cacheclear/{stockname}")
async def clear_cache(stockname: str, ticker: str = None):
    # Clear Core and Satellite Caches
    core_key = cache_manager.get_analysis_key(stockname, "core")
    satellite_key = cache_manager.get_analysis_key(stockname, "sattelite")
    cache_manager.delete(core_key)
    cache_manager.delete(satellite_key)
    
    # Clear Tech Cache (try both stockname and ticker if available)
    tech_key_name = cache_manager.get_tech_data_key(stockname)
    cache_manager.delete(tech_key_name)
    
    # Clear Data Caches if ticker is provided
    if ticker and ticker.strip():
        raw_key = cache_manager.get_raw_data_key(ticker)
        tech_key_ticker = cache_manager.get_tech_data_key(ticker)
        cache_manager.delete(raw_key)
        cache_manager.delete(tech_key_ticker)
        print(f"Cleared all cache for {stockname} (Ticker: {ticker})")
    else:
        print(f"Cleared core and tech (stockname-based) cache for {stockname}")
        
    return {"success": True, "message": f"Cache cleared for {stockname}"}

@app.post("/analyzeall/{portfolio_type}")
async def analyze_all(portfolio_type: str, body: BatchAnalysisRequest):
    return orchestrator.rank_all(body.data, portfolio_type)

@app.post("/sattelite/analyze")
async def analyze_sattelite(file: UploadFile = File(...)):
    try:
        df = await FileUtil.to_dataframe(file)
        # Placeholder for satellite analysis logic
        return {
            "success": True, 
            "filename": file.filename,
            "rows": len(df),
            "columns": list(df.columns),
            "message": "File converted to DataFrame successfully"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
