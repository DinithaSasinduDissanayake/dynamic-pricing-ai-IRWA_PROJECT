import asyncio
import sys
from core.auth_db import create_db_and_tables

async def main():
    print("Initializing Auth DB...")
    try:
        await create_db_and_tables()
        print("Auth DB initialized successfully.")
    except Exception as e:
        print(f"Error initializing Auth DB: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
