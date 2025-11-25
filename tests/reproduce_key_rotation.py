import asyncio
import os
import sys
import logging
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.append(os.getcwd())

from core.agents.llm_client import LLMClient

# Setup logging
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("core.agents.llm")
logger.setLevel(logging.INFO)

async def mock_acompletion(*args, **kwargs):
    api_key = kwargs.get("api_key")
    print(f"[MockLLM] Received request with key: {api_key}")
    
    if api_key == "KEY_1":
        print("[MockLLM] Simulating 429 for KEY_1")
        raise Exception("429 Rate Limit Exceeded")
    elif api_key == "KEY_2":
        print("[MockLLM] Simulating 429 for KEY_2")
        raise Exception("429 Rate Limit Exceeded")
    elif api_key == "KEY_3":
        print("[MockLLM] Success for KEY_3")
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "I'm alive!"
        return mock_resp
    else:
        print(f"[MockLLM] Unknown key: {api_key}")
        return MagicMock()

async def test_rotation():
    print("--- Starting Key Rotation Test ---")
    
    # Set up environment with dummy keys
    os.environ["DEFAULT_LLM_MODEL"] = "gemini/gemini-pro"
    os.environ["GEMINI_API_KEY_1"] = "KEY_1"
    os.environ["GEMINI_API_KEY_2"] = "KEY_2"
    os.environ["GEMINI_API_KEY_3"] = "KEY_3"
    
    # Initialize client
    client = LLMClient()
    
    if client.key_manager:
        print(f"Discovered keys: {[k['key'] for k in client.key_manager.keys]}")
    else:
        print("KeyManager not initialized!")
        return

    # Patch acompletion
    with patch("core.agents.llm_client.acompletion", side_effect=mock_acompletion):
        try:
            response = await client.chat(messages=[{"role": "user", "content": "hi"}])
            print(f"Final Response: {response}")
        except Exception as e:
            print(f"Test failed with exception: {e}")

    # Verify stats
    stats = client.key_manager.get_stats()
    print(f"Key Manager Stats: {stats}")
    
    zombies = [k for k in client.key_manager.keys if k['status'] == 'zombie']
    print(f"Zombies: {[k['key'] for k in zombies]}")

if __name__ == "__main__":
    asyncio.run(test_rotation())
