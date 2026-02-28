import json
from pathlib import Path
from llm.llm import get_llm_instance

class BuyAddSellAgent:
    """
    Agent responsible for providing a Buy, Add, Sell, or None decision
    based on Technical Analysis and Stage Analysis data.
    """
    def __init__(self):
        self.llm = get_llm_instance()
        self.prompt_path = Path(__file__).parent / "buy_add_sell.md"

    def execute(self, stock_name: str, technical_data: dict, stage_data: any, portfolio_type: str = "core"):
        """
        Evaluates the stock and returns a decision with reasoning.
        """
        prompt_filename = "buy_add_sell_sat.md" if portfolio_type.lower() == "sattelite" else "buy_add_sell.md"
        curr_prompt_path = Path(__file__).parent / prompt_filename

        if not curr_prompt_path.exists():
            return {"Decision": "None", "Reasoning": f"Prompt file {prompt_filename} missing."}

        with open(curr_prompt_path, "r") as f:
            template = f.read()

        # Prepare stage data string for the prompt
        stage_str = json.dumps(stage_data, indent=2) if stage_data else "No stage data available."
        tech_str = json.dumps(technical_data, indent=2) if technical_data else "No technical data available."

        prompt = template.replace("{{stock_name}}", stock_name)
        prompt = prompt.replace("{{technical_data}}", tech_str)
        prompt = prompt.replace("{{stage_data}}", stage_str)

        try:
            response = self.llm.completion(
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            return {
                "decision": result.get("Decision") or result.get("decision") or "None",
                "reasoning": result.get("Reasoning") or result.get("reasoning") or "No reasoning provided."
            }
        except Exception as e:
            print(f"Buy/Add/Sell evaluation failed for {stock_name}: {e}")
            return {
                "decision": "None",
                "reasoning": f"LLM Error: {str(e)}"
            }
