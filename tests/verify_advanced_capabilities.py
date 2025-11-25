import asyncio
import os
import sys
from typing import List, Dict, Any

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.agents.user_interact.user_interaction_agent import UserInteractionAgent
from core.agents.llm_client import get_llm_client

# Mock tools if needed, or rely on real ones. 
# For verification, we just want to see the "tool_call" event.

async def run_test_prompt(prompt: str, expected_tool: str):
    print(f"\n--- Testing Prompt: '{prompt}' ---")
    print(f"Expecting tool: {expected_tool}")
    
    agent = UserInteractionAgent(user_name="TestUser", mode="user")
    
    tool_called = False
    response_text = ""
    
    print("Agent Stream:")
    try:
        async for chunk in agent.stream_response(prompt):
            if isinstance(chunk, dict):
                if chunk.get("type") == "tool_call":
                    tname = chunk.get("name")
                    status = chunk.get("status")
                    if status == "start":
                        print(f"  [TOOL START] {tname}")
                        if tname == expected_tool:
                            tool_called = True
                    elif status == "end":
                        print(f"  [TOOL END] {tname}")
                elif chunk.get("type") == "agent":
                    print(f"  [AGENT] {chunk.get('name')}")
            else:
                # Text chunk
                print(chunk, end="", flush=True)
                response_text += chunk
    except Exception as e:
        print(f"\nError: {e}")
        
    print("\n")
    
    if tool_called:
        print(f"✅ SUCCESS: Tool '{expected_tool}' was called.")
    else:
        print(f"❌ FAILURE: Tool '{expected_tool}' was NOT called.")
        # Debug: check if LLM client is available
        llm = get_llm_client()
        if not llm.is_available():
            print("  (LLM Client reported unavailable)")

async def main():
    # Test 1: Inventory Listing
    await run_test_prompt("List all my inventory items.", "list_inventory_items")
    
    # Test 2: Price Optimization (Mocking a SKU)
    # We expect it to try to optimize, even if SKU doesn't exist
    await run_test_prompt("Optimize the price for product SKU-123.", "optimize_price")

if __name__ == "__main__":
    # Load env vars if needed
    from dotenv import load_dotenv
    load_dotenv()
    
    asyncio.run(main())
