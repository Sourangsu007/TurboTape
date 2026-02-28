import json
from pathlib import Path
from llm.llm import get_llm_instance

class StageAnalysisAgent:
    """
    Agent responsible for performing stage analysis on a stock.
    """
    def __init__(self):
        self.llm = get_llm_instance()
        self.prompt_path = Path(__file__).parent / "Staging_prompt.md"

    def execute(self, stock_name: str, financial_data: dict, industry: str):
        """
        Executes the stage analysis call to the LLM.
        """
        if not self.prompt_path.exists():
            raise FileNotFoundError(f"Staging prompt file not found at {self.prompt_path}")
            
        with open(self.prompt_path, "r") as f:
            template = f.read()
            
        prompt = template.replace("{{stock_name}}", stock_name)
        prompt = prompt.replace("{{industry}}", industry)
        prompt = prompt.replace("{{financial_data}}", json.dumps(financial_data, indent=2))
        
        response = self.llm.completion(
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        
        try:
            result = json.loads(response.choices[0].message.content)
            return {
                "success": True,
                "stage_analysis": result
            }
        except json.JSONDecodeError:
            return {
                "success": False,
                "error": "LLM failed to return valid JSON for stage analysis"
            }
