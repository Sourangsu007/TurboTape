import json
from pathlib import Path
from llm.llm import get_llm_instance

class RankingAgent:
    """
    Agent responsible for ranking multiple stocks based on combined analysis results.
    """
    def __init__(self):
        self.llm = get_llm_instance()
        self.prompt_path = Path(__file__).parent / "ranking_prompt.md"

    def execute_batch(self, analysis_results: list):
        """
        Executes a comparative ranking across multiple stock analysis results.
        """
        if not self.prompt_path.exists():
            raise FileNotFoundError(f"Ranking prompt file not found at {self.prompt_path}")
            
        with open(self.prompt_path, "r") as f:
            template = f.read()
            
        # We'll use a specific placeholder for the batch data
        prompt = template.replace("{{batch_data}}", json.dumps(analysis_results, indent=2))
        
        # If the template still has single-stock placeholders, we'll just leave them or clear them
        # (The user will finalize the prompt content)
        
        response = self.llm.completion(
            messages=[{"role": "system", "content": "You are a Senior Technical and Fundamental Analyst specializing in stock ranking."},
                      {"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        
        try:
            result = json.loads(response.choices[0].message.content)
            # Handle both {"ranking_results": [...]} and bare [...] formats
            if isinstance(result, dict):
                rankings = result.get("ranking_results", result.get("rankings", []))
            elif isinstance(result, list):
                rankings = result
            else:
                rankings = []
            return {
                "success": True,
                "ranking_results": rankings
            }
        except json.JSONDecodeError:
            return {
                "success": False,
                "error": "LLM failed to return valid JSON for batch ranking analysis"
            }
