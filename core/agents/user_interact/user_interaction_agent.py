import os
import logging
from typing import Optional, List, Any, Dict
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

logger = logging.getLogger(__name__)

if 'load_dotenv' in globals() and callable(load_dotenv):
    load_dotenv()

try:
    from core.agents.llm_client import get_llm_client
except Exception as e:
    print(f"DEBUG: Failed to import get_llm_client: {e}")
    get_llm_client = None

try:
    from .tools import TOOLS_MAP
except Exception:
    TOOLS_MAP = {}

try:
    from .prompts import get_system_prompt
except Exception:
    get_system_prompt = None

try:
    from .tool_schemas import TOOL_SCHEMAS, get_agent_for_tool
except Exception:
    TOOL_SCHEMAS = []
    get_agent_for_tool = lambda name: ""

try:
    from core.settings import get_settings
except Exception:
    def get_settings():
        class _S: pass
        return _S()

class UserInteractionAgent:
    def __init__(self, user_name, mode: str = "user", owner_id: Optional[str] = None):
        self.user_name = user_name
        self.mode = (mode or "user").lower()
        self.owner_id = owner_id
        self.memory = []
        self.last_model = None
        self.last_provider = None
        self.last_usage = {}

    def add_to_memory(self, role, content):
        self.memory.append({"role": role, "content": content})

    async def stream_response(self, message):
        if not self.memory or self.memory[-1].get("role") != "user" or self.memory[-1].get("content") != message:
            self.add_to_memory("user", message)

        # Set context if needed (simplified)
        if self.owner_id:
            try:
                from .context import set_owner_id
                set_owner_id(str(self.owner_id))
            except Exception:
                pass

        system_prompt = get_system_prompt(self.mode) if get_system_prompt else "You are a helpful assistant."
        
        if not get_llm_client:
            yield "LLM client not available."
            return

        llm = get_llm_client()
        if not llm.is_available():
            yield "LLM not available."
            return

        msgs = [{"role": "system", "content": system_prompt}]
        msgs.extend(self.memory)
        
        # Simple token limit logic
        max_tokens = 1024
        try:
            s = get_settings()
            mt = getattr(s, "ui_llm_max_tokens", None)
            if mt: max_tokens = mt
        except Exception:
            pass

        # Tool Loop
        max_rounds = 3
        try:
            from langchain_core.messages import AIMessageChunk
        except ImportError:
            yield "Error: langchain_core not found."
            return

        for _ in range(max_rounds):
            full_response_content = []
            aggregated_chunk = None
            
            # Stream from LLM
            async for chunk in llm.chat_with_tools_stream(
                messages=msgs,
                tools=TOOL_SCHEMAS,
                max_tokens=max_tokens
            ):
                if aggregated_chunk is None:
                    aggregated_chunk = chunk
                else:
                    aggregated_chunk += chunk
                
                if chunk.content:
                    text_content = chunk.content
                    if isinstance(text_content, list):
                        # Handle case where content is a list (e.g. multimodal)
                        text_content = "".join([str(item) for item in text_content])
                    elif not isinstance(text_content, str):
                        text_content = str(text_content)
                        
                    full_response_content.append(text_content)
                    yield text_content

            if aggregated_chunk is None:
                break

            # Check for tool calls
            if not aggregated_chunk.tool_calls:
                # No tools, we are done
                final_content = "".join(full_response_content)
                self.add_to_memory("assistant", final_content)
                break
            
            # Handle tool calls
            # Add assistant message with tool calls to history
            # We need to convert LangChain message to our dict format or just keep using msgs list for next turn
            # But self.memory is dicts. We should update self.memory.
            
            # Note: self.memory stores simple dicts. It doesn't support tool_calls natively in this simple dict structure yet?
            # core/chat_db.py schema supports 'agents' and 'tools' metadata but the message content is text.
            # We should probably just append the text content to memory.
            # But for the NEXT turn, we need to pass the tool calls to the LLM.
            # The LLMClient._convert_messages handles "tool_calls" key in assistant message.
            
            assistant_msg = {
                "role": "assistant",
                "content": aggregated_chunk.content or "",
                "tool_calls": aggregated_chunk.tool_calls
            }
            msgs.append(assistant_msg)
            # We don't add intermediate tool calls to self.memory (which is persisted to DB) 
            # because the DB schema might not handle them well or we want to hide them?
            # Actually, we should probably persist them if we want full history.
            # But for now, let's just keep them in `msgs` for the loop.
            
            # Execute tools
            for tool_call in aggregated_chunk.tool_calls:
                function_name = tool_call["name"]
                function_args = tool_call["args"]
                
                # Yield tool call event
                yield {"type": "tool_call", "name": function_name, "status": "start"}
                
                content = ""
                if function_name in TOOLS_MAP:
                    import inspect
                    try:
                        func = TOOLS_MAP[function_name]
                        # Check if we need to inject owner_id or context? 
                        # The tools usually get it from context or args.
                        
                        if inspect.iscoroutinefunction(func):
                            result = await func(**function_args)
                        else:
                            result = func(**function_args)
                        content = str(result)
                    except Exception as e:
                        content = f"Error executing {function_name}: {e}"
                else:
                    content = f"Error: Function {function_name} not found"
                
                yield {"type": "tool_call", "name": function_name, "status": "end"}
                
                # Add tool result to msgs
                msgs.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "name": function_name,
                    "content": content
                })
                
                # Also yield agent activation event if mapped
                agent_name = get_agent_for_tool(function_name)
                if agent_name:
                    yield {"type": "agent", "name": agent_name}

        # End of loop

