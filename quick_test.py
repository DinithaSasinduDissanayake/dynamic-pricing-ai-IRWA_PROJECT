import asyncio
from litellm import acompletion

async def test():
    key = "AIzaSyCX4lqH-XD2xOspAdpWogc-ms1-ukHlUxE"
    model = "gemini/gemini-2.0-flash"
    
    print(f"Testing {model} with litellm...")
    
    try:
        response = await acompletion(
            model=model,
            messages=[{"role": "user", "content": "Say hello"}],
            api_key=key
        )
        print(f"[SUCCESS] {response.choices[0].message.content}")
        return True
    except Exception as e:
        print(f"[FAIL] {str(e)[:300]}")
        return False

if __name__ == "__main__":
    result = asyncio.run(test())
    print(f"\nTest {'PASSED' if result else 'FAILED'}")
