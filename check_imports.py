import sys
import traceback

try:
    print("Importing core.auth_db...")
    import core.auth_db
    print("Importing backend.main...")
    import backend.main
    print("Success!")
except Exception:
    traceback.print_exc()
