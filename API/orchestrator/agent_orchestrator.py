from agents.initial_screening.initial_screening_agent import InitialScreeningAgent
from agents.stage_analysis.stage_analysis_agent import StageAnalysisAgent
from agents.ranking_agent.ranking_agent import RankingAgent
from agents.technical_analysis.TechnicalAnalysisHelper import TechnicalAnalysisHelper
from agents.technical_analysis.buy_add_sell import BuyAddSellAgent
from caching.cache_manager import cache_manager

class AgentOrchestrator:
    """
    Orchestrator class to manage and coordinate the execution of multiple agents.
    """
    def __init__(self):
        # Initialize agents that the orchestrator will manage
        self.initial_screening_agent = InitialScreeningAgent()
        self.stage_analysis_agent = StageAnalysisAgent()
        self.ranking_agent = RankingAgent()
        self.technical_helper = TechnicalAnalysisHelper()
        self.buy_add_sell_agent = BuyAddSellAgent()

    def rank_all(self, data: list):
        """
        Ranks a collection of analyzed stock data.
        """
        return self.ranking_agent.execute_batch(data)

    def execute(self, stock_name: str, data: any):
        """
        Coordinates the execution of agents for a specific stock analysis task.
        """
        print(f"Orchestrating analysis for: {stock_name} (Purpose: {data.purpose})")
        
        # Phase 1: Initial Screening
        print("Starting Initial Screening Phase...")
        screening_result = self.initial_screening_agent.execute(stock_name)
        
        if not screening_result.get("success"):
            return screening_result
        ticker_name=screening_result.get("ticker_name", "")
        # Phase 2: Stage Analysis
        print("Starting Stage Analysis Phase...")
        stage_result = self.stage_analysis_agent.execute(
            stock_name=stock_name,
            financial_data=screening_result.get("financial_data", {}),
            industry=screening_result.get("industry", "Unknown")
        )

        # Phase 3: Technical Analysis
        print("Starting Technical Analysis Phase...")
        tech_cache_key = cache_manager.get_tech_data_key(ticker_name)
        technical_result = cache_manager.get(tech_cache_key)
        
        if technical_result:
            print(f"Layer 2 Cache Hit (Tech): {tech_cache_key}")
        else:
            try:
                technical_result = self.technical_helper.get_technical_analysis(ticker_name, as_dict=True)
                if not technical_result.get("error"):
                    cache_manager.set(tech_cache_key, technical_result, expire=cache_manager.expire_data)
            except Exception as e:
                print(f"Technical Analysis failed for {stock_name}: {e}")
                technical_result = {"error": str(e)}

        # Phase 4: Buy/Add/Sell Decision
        print("Starting Buy/Add/Sell Decision Phase...")
        decision_result = self.buy_add_sell_agent.execute(
            stock_name=stock_name,
            technical_data=technical_result,
            stage_data=stage_result.get("stage_analysis")
        )

        # Combine Results
        final_result = screening_result.copy()
        if stage_result.get("success"):
            final_result["stage_analysis"] = stage_result.get("stage_analysis")
        else:
            final_result["stage_analysis_error"] = stage_result.get("error")

        final_result["technical_analysis"] = technical_result
        final_result["analysis_decision"] = decision_result

        return final_result
