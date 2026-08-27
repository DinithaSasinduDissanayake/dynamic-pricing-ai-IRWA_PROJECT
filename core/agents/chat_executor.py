from __future__ import annotations

from typing import Any, Dict, List, Callable, Optional
import json
from datetime import datetime


class ChatExecutor:
    def __init__(self, log):
        self._log = log

    def execute_tool_call(
        self,
        fn_name: Optional[str],
        raw_args: str,
        functions_map: Dict[str, Callable[..., Any]],
        tools_used: List[str],
        trace_id: Optional[str] = None,
    ) -> Any:
        try:
            if fn_name and fn_name not in tools_used:
                tools_used.append(fn_name)
        except Exception:
            pass

        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            if not isinstance(args, dict):
                raise ValueError(f"expected a JSON object of arguments, got {type(args).__name__}")
        except Exception as parse_exc:
            return {
                "ok": False,
                "error": f"invalid arguments for {fn_name}: could not parse tool arguments as JSON object ({parse_exc})",
            }

        # Typed boundary: validate arguments against the tool's Pydantic model
        # before touching the implementation (error-as-message on failure).
        try:
            from .user_interact.tool_models import validate_tool_args
        except Exception:
            validate_tool_args = None
        if validate_tool_args is not None:
            ok, validated = validate_tool_args(fn_name or "", args)
            if not ok:
                self._log.warning("Tool argument validation failed for %s: %s", fn_name, validated.get("error"))
                return validated
            args = validated

        tool_start_time = datetime.now()
        result: Any
        error_occurred = False

        if fn_name in functions_map:
            try:
                result = functions_map[fn_name](**args)
            except TypeError:
                result = functions_map[fn_name](args)
            except Exception as tool_exc:
                result = {"error": str(tool_exc)}
                error_occurred = True

            if hasattr(result, '__await__'):
                import asyncio
                from concurrent.futures import ThreadPoolExecutor

                def run_in_new_loop():
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        return new_loop.run_until_complete(result)
                    finally:
                        new_loop.close()

                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(run_in_new_loop)
                    result = future.result()
        else:
            result = {"error": f"unknown tool: {fn_name}"}
            error_occurred = True

        try:
            if trace_id:
                duration_ms = int((datetime.now() - tool_start_time).total_seconds() * 1000)
                status = "failed" if error_occurred else "completed"
                self._log.debug(f"Tool call {status}: {fn_name} duration={duration_ms}ms")
        except Exception:
            pass

        return result

    @staticmethod
    def serialize_tool_result(result: Any) -> str:
        try:
            return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        except Exception:
            return str(result)
