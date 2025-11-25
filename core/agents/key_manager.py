import os
import time
import random
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class KeyManager:
    """
    The Juggler: Manages multiple API keys with a cheeky attitude.
    Handles rotation, cooldowns (Zombie Mode), and dynamic discovery.
    """

    def __init__(self, provider_prefix: str = "GEMINI_API_KEY"):
        self.provider_prefix = provider_prefix
        self.keys: List[Dict[str, any]] = []
        self._discover_keys()
        self.cooldown_seconds = 60

    def _discover_keys(self):
        """Hunts for keys in the environment wildlands."""
        found = []
        # Check for the OG key
        if os.getenv(self.provider_prefix):
            found.append(os.getenv(self.provider_prefix))
        
        # Hunt for the clones (GEMINI_API_KEY_1, _SECRET, etc.)
        for key, value in os.environ.items():
            if key.startswith(f"{self.provider_prefix}_") and value:
                found.append(value)
        
        # Deduplicate just in case
        unique_keys = list(set(found))
        
        for k in unique_keys:
            self.keys.append({
                "key": k,
                "status": "alive", # alive, zombie
                "cooldown_until": 0,
                "usage_count": 0
            })
            
        if not self.keys:
            logger.warning(f"No keys found for {self.provider_prefix}. We are flying blind, captain!")
        else:
            logger.info(f"Discovered {len(self.keys)} keys. Let the juggling begin!")

    def get_key(self) -> Optional[str]:
        """
        Returns a living key. If all are zombies, tries to resurrect the oldest one.
        """
        if not self.keys:
            return None

        current_time = time.time()
        
        # 1. Try to find a living key
        living_keys = [k for k in self.keys if k["status"] == "alive"]
        
        if living_keys:
            # Weighted random selection? Nah, let's just pick one.
            # Actually, let's pick the one with least usage to balance the load
            living_keys.sort(key=lambda x: x["usage_count"])
            selected = living_keys[0]
            selected["usage_count"] += 1
            return selected["key"]

        # 2. All keys are zombies? Check if any can be resurrected
        zombies = [k for k in self.keys if k["status"] == "zombie"]
        ready_to_rise = [k for k in zombies if k["cooldown_until"] <= current_time]
        
        if ready_to_rise:
            # Resurrect the one that's been dead the longest (lowest cooldown_until)
            ready_to_rise.sort(key=lambda x: x["cooldown_until"])
            risen = ready_to_rise[0]
            risen["status"] = "alive"
            risen["cooldown_until"] = 0
            logger.info(f"Resurrecting a key from the void! It lives!")
            risen["usage_count"] += 1
            return risen["key"]

        # 3. Desperate times: Zombie Mode (Force resurrection of the oldest zombie)
        # If we are here, all keys are zombies and none are ready.
        # We'll pick the one that expires soonest and force it.
        # Or just wait? The user wants "cheeky", so let's force it but warn.
        if zombies:
            zombies.sort(key=lambda x: x["cooldown_until"])
            desperate_choice = zombies[0]
            wait_time = desperate_choice["cooldown_until"] - current_time
            if wait_time > 0:
                logger.warning(f"All keys are dead. Desperately summoning one that should sleep for {wait_time:.1f}s more.")
            
            desperate_choice["status"] = "alive"
            desperate_choice["usage_count"] += 1
            return desperate_choice["key"]
            
        return None

    def report_error(self, key_value: str, error_code: int):
        """
        Snitches on a key that failed.
        """
        for k in self.keys:
            if k["key"] == key_value:
                if error_code == 429:
                    k["status"] = "zombie"
                    k["cooldown_until"] = time.time() + self.cooldown_seconds
                    logger.warning(f"Key hit a wall (429). It's taking a nap for {self.cooldown_seconds}s.")
                else:
                    # Maybe other errors shouldn't kill the key?
                    pass
                break

    def get_stats(self):
        return {
            "total": len(self.keys),
            "alive": len([k for k in self.keys if k["status"] == "alive"]),
            "zombies": len([k for k in self.keys if k["status"] == "zombie"])
        }
