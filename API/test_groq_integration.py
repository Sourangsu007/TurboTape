import os
from unittest.mock import patch, MagicMock
from llm.llm import LiteLLMWrapper

def test_groq_configuration():
    print("Testing Groq Configuration...")
    wrapper = LiteLLMWrapper(provider="groq", model_name="llama3-8b-8192")
    
    # Check if provider is correctly set
    assert wrapper.provider == "groq"
    assert wrapper.model_name == "llama3-8b-8192"
    print("✓ Groq provider and model name set correctly.")

    # Mock litellm.completion to check if it's called with the right parameters
    with patch('litellm.completion') as mock_completion:
        mock_completion.return_value = MagicMock()
        messages = [{"role": "user", "content": "Hello"}]
        
        wrapper.completion(messages)
        
        # Verify it prefixes with 'groq/'
        mock_completion.assert_called_once()
        args, kwargs = mock_completion.call_args
        assert kwargs['model'] == "groq/llama3-8b-8192"
        print("✓ Groq model prefixing verified.")

if __name__ == "__main__":
    try:
        test_groq_configuration()
        print("\nAll Groq integration tests passed!")
    except Exception as e:
        print(f"\nTests failed: {e}")
        exit(1)
