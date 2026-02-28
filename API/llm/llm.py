"""
ResilientLLM
============
A resilient LLM wrapper using LiteLLM Router with an explicit ordered
fallback chain:

    gemini-2.5-flash  →  llama-3.3-70b (Groq)  →  llama-4-scout (Groq)

All model names and API keys come from config.yaml.
API keys are resolved from environment variables at runtime via the
"os.environ/KEY_NAME" syntax — never hardcoded.

Usage
-----
    llm = ResilientLLM()                        # loads config.yaml from default path
    llm = ResilientLLM(config_path="my.yaml")   # custom path

    response = llm.completion([
        {"role": "user", "content": "Analyse RELIANCE stock fundamentals."}
    ])
    print(response.choices[0].message.content)
"""

import os
import logging
import yaml
import litellm
from litellm import Router

logger = logging.getLogger(__name__)

# Suppress LiteLLM's verbose success logs — keep WARNING and above only.
# Comment this out if you want to see which model was actually used.
litellm.suppress_debug_info = True
logging.getLogger("LiteLLM").setLevel(logging.WARNING)


class ResilientLLM:
    """
    LiteLLM Router wrapper with explicit ordered fallback.

    The fallback chain is driven entirely by config.yaml — no logic
    is hardcoded here.  Swap models or change order by editing the YAML.

    Parameters
    ----------
    config_path : str
        Path to config.yaml.  Defaults to a 'config.yaml' file sitting in
        the same directory as this Python file.
    """

    # Name of the entry-point model in config.yaml — the router always
    # starts here and follows the fallbacks list if it fails.
    _PRIMARY_MODEL = "llm-primary"

    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "config.yaml"
            )

        if not os.path.exists(config_path):
            raise FileNotFoundError(
                f"ResilientLLM: config file not found at '{config_path}'"
            )

        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f)

        model_list    = config_data.get("model_list", [])
        settings      = config_data.get("router_settings", {})
        fallbacks     = settings.get("fallbacks", [])
        num_retries   = int(settings.get("num_retries", 1))

        if not model_list:
            raise ValueError("ResilientLLM: 'model_list' is empty in config.yaml")

        self.router = Router(
            model_list  = model_list,
            fallbacks   = fallbacks,   # explicit ordered chain: primary → secondary → tertiary
            num_retries = num_retries, # retries per model before moving to next fallback
            # Timeout for a single model attempt (seconds).
            # If a model hangs longer than this, it's treated as a failure
            # and the next fallback is tried.
            timeout     = 30,
        )

        # Log which models are loaded so startup issues are obvious
        names = [m.get("model_name") for m in model_list]
        logger.info(f"ResilientLLM initialised. Models: {names}. Fallbacks: {fallbacks}")

    # =========================================================================
    # PUBLIC
    # =========================================================================

    def completion(self, messages: list, **kwargs) -> litellm.ModelResponse:
        """
        Send a chat completion request.  The Router automatically tries
        llm-primary first, then falls back through the chain defined in
        config.yaml if any model fails or times out.

        Parameters
        ----------
        messages : list of {"role": ..., "content": ...} dicts
        **kwargs : any extra litellm.completion() params
                   e.g. temperature=0.3, max_tokens=1024, stream=False

        Returns
        -------
        litellm.ModelResponse  (same shape as OpenAI ChatCompletion response)

        Raises
        ------
        Exception  if every model in the fallback chain fails
        """
        try:
            # Groq/LiteLLM JSON mode safety: Groq requires 'json' in the prompt for json_object format.
            if kwargs.get("response_format") == {"type": "json_object"}:
                json_found = False
                for m in messages:
                    content = m.get("content", "")
                    if isinstance(content, str) and "json" in content.lower():
                        json_found = True
                        break
                
                if not json_found:
                    logger.info("ResilientLLM: Injecting 'json' requirement for Groq compatibility.")
                    # Append it to the last user message or add a new system message
                    messages.append({
                        "role": "system", 
                        "content": "CRITICAL: The output must be valid JSON."
                    })

            response = self.router.completion(
                model    = self._PRIMARY_MODEL,
                messages = messages,
                **kwargs,
            )
            logger.info(
                f"ResilientLLM: success via model='{response.model}'"
            )
            return response

        except Exception as e:
            logger.error(f"ResilientLLM: all models in fallback chain failed. Error: {e}")
            raise

    def completion_text(self, messages: list, **kwargs) -> str:
        """
        Convenience wrapper — returns the response text directly as a string
        instead of the full ModelResponse object.

        Parameters
        ----------
        messages : list of {"role": ..., "content": ...} dicts
        **kwargs : forwarded to completion()

        Returns
        -------
        str  — content of the first choice message
        """
        response = self.completion(messages, **kwargs)
        return response.choices[0].message.content


# ─────────────────────────────────────────────────────────────────────────────
# Factory helper — convenience function for importing in other modules
# ─────────────────────────────────────────────────────────────────────────────

def get_llm_instance(config_path: str = None) -> ResilientLLM:
    """
    Return a ready-to-use ResilientLLM instance.

    config_path is optional.  If not provided, looks for config.yaml in the
    same directory as this file.

    Usage
    -----
        from resilient_llm import get_llm_instance

        llm = get_llm_instance()
        text = llm.completion_text([{"role": "user", "content": "Hello"}])
    """
    return ResilientLLM(config_path="./config.yaml")