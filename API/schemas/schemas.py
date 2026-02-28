from pydantic import BaseModel
from typing import Literal, List, Any

class AnalyzeStock(BaseModel):
    portfolio_type: Literal["Core", "Satellite"]
    purpose: Literal["buy", "add", "sell"]

class BatchAnalysisRequest(BaseModel):
    data: List[Any]
