from __future__ import annotations

import os
import logging
import asyncio
from typing import Optional, Any, Dict, List, Callable, Union
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage, ToolMessage
from langchain_core.tools import tool
from core.agents.key_manager import KeyManager

class LLMClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self._log = logging.getLogger("core.agents.llm")
        self.raw_model = model or os.getenv("DEFAULT_LLM_MODEL", "gemini-2.0-flash")
        # Strip provider prefix if present (e.g. gemini/gemini-2.0-flash -> gemini-2.0-flash)
        self.model = self.raw_model.split("/")[-1] if "/" in self.raw_model else self.raw_model
        self.base_url = base_url
        
        # Initialize KeyManager if using Gemini
        self.key_manager = None
        if "gemini" in self.model.lower():
            self.key_manager = KeyManager(provider_prefix="GEMINI_API_KEY")
        
        self.api_key = api_key
        self.last_usage: Dict[str, Any] = {}

    def is_available(self) -> bool:
        return True

    def provider(self) -> str:
        return "gemini" if "gemini" in self.model.lower() else "openai"

    def _get_api_key(self) -> Optional[str]:
        if self.key_manager:
            k = self.key_manager.get_key()
            if k: return k
            self._log.warning("KeyManager returned no keys! Zombie apocalypse?")
        return self.api_key

    def _convert_messages(self, messages: List[Dict[str, Any]]) -> List[BaseMessage]:
        lc_messages = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content") or ""
            if role == "user":
                lc_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    # Handle tool calls in assistant message
                    lc_messages.append(AIMessage(content=content, tool_calls=tool_calls))
                else:
                    lc_messages.append(AIMessage(content=content))
            elif role == "system":
                lc_messages.append(SystemMessage(content=content))
            elif role == "tool":
                lc_messages.append(ToolMessage(
                    content=content,
                    tool_call_id=msg.get("tool_call_id"),
                    name=msg.get("name")
                ))
        return lc_messages

    async def chat(self, messages: List[Dict[str, str]], max_tokens: int = 256, temperature: float = 0.2) -> str:
        retries = 3
        for attempt in range(retries):
            current_key = self._get_api_key()
            try:
                llm = ChatGoogleGenerativeAI(
                    model=self.model,
                    google_api_key=current_key,
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                    convert_system_message_to_human=True # Gemini sometimes needs this
                )
                
                lc_messages = self._convert_messages(messages)
                response = await llm.ainvoke(lc_messages)
                
                self._capture_usage(response)
                return response.content
            except Exception as e:
                is_rate_limit = "429" in str(e) or "ResourceExhausted" in str(e)
                if is_rate_limit and self.key_manager:
                    self._log.warning(f"Hit rate limit with key ending in ...{current_key[-4:] if current_key else 'None'}. Rotating.")
                    self.key_manager.report_error(current_key, 429)
                    if attempt < retries - 1:
                        continue
                self._log.error(f"LLM chat failed: {e}")
                raise

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int = 256,
        temperature: float = 0.2,
    ):
        retries = 3
        for attempt in range(retries):
            current_key = self._get_api_key()
            started = False
            try:
                llm = ChatGoogleGenerativeAI(
                    model=self.model,
                    google_api_key=current_key,
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                    convert_system_message_to_human=True
                )
                
                lc_messages = self._convert_messages(messages)
                async for chunk in llm.astream(lc_messages):
                    started = True
                    if chunk.content:
                        yield chunk.content
                return
            except Exception as e:
                if started:
                    self._log.error(f"Stream broke mid-flight: {e}")
                    raise e
                
                is_rate_limit = "429" in str(e) or "ResourceExhausted" in str(e)
                if is_rate_limit and self.key_manager:
                    self._log.warning(f"Stream start hit rate limit. Rotating key.")
                    self.key_manager.report_error(current_key, 429)
                    if attempt < retries - 1:
                        continue
                self._log.error(f"LLM stream failed: {e}")
                raise

    async def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        functions_map: Dict[str, Callable[..., Any]],
        tool_choice: Optional[str] = "auto",
        max_rounds: int = 3,
        max_tokens: int = 256,
        temperature: float = 0.2,
        trace_id: Optional[str] = None,
    ) -> str:
        current_messages = self._convert_messages(messages)
        
        retries = 3
        for attempt in range(retries):
            current_key = self._get_api_key()
            try:
                llm = ChatGoogleGenerativeAI(
                    model=self.model,
                    google_api_key=current_key,
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                    convert_system_message_to_human=True
                )
                
                # Bind tools
                llm_with_tools = llm.bind_tools(tools)
                
                # We need a loop for tool execution (Agent-like loop)
                for _ in range(max_rounds):
                    response = await llm_with_tools.ainvoke(current_messages)
                    self._capture_usage(response)
                    
                    current_messages.append(response)
                    
                    if not response.tool_calls:
                        return response.content
                    
                    # Execute tools
                    for tool_call in response.tool_calls:
                        function_name = tool_call["name"]
                        function_args = tool_call["args"]
                        
                        content = ""
                        if function_name in functions_map:
                            import inspect
                            try:
                                func = functions_map[function_name]
                                if inspect.iscoroutinefunction(func):
                                    result = await func(**function_args)
                                else:
                                    result = func(**function_args)
                                content = str(result)
                            except Exception as e:
                                content = f"Error executing {function_name}: {e}"
                        else:
                            content = f"Error: Function {function_name} not found"
                            
                        current_messages.append(ToolMessage(
                            content=content,
                            tool_call_id=tool_call["id"],
                            name=function_name
                        ))
                
                return "Max tool rounds exceeded"

            except Exception as e:
                is_rate_limit = "429" in str(e) or "ResourceExhausted" in str(e)
                if is_rate_limit and self.key_manager:
                    self.key_manager.report_error(current_key, 429)
                    if attempt < retries - 1:
                        continue
                raise e

    async def chat_with_tools_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int = 256,
        temperature: float = 0.2,
    ):
        """
        Streams response with tool binding. 
        Yields chunks. Caller is responsible for aggregating tool calls and handling the loop.
        """
        retries = 3
        for attempt in range(retries):
            current_key = self._get_api_key()
            try:
                llm = ChatGoogleGenerativeAI(
                    model=self.model,
                    google_api_key=current_key,
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                    convert_system_message_to_human=True
                )
                
                llm_with_tools = llm.bind_tools(tools)
                lc_messages = self._convert_messages(messages)
                
                async for chunk in llm_with_tools.astream(lc_messages):
                    yield chunk
                return

            except Exception as e:
                is_rate_limit = "429" in str(e) or "ResourceExhausted" in str(e)
                if is_rate_limit and self.key_manager:
                    self.key_manager.report_error(current_key, 429)
                    if attempt < retries - 1:
                        continue
                raise e

    def _capture_usage(self, response: Any):
        try:
            if hasattr(response, "usage_metadata"):
                self.last_usage = {
                    "prompt_tokens": response.usage_metadata.get("input_tokens", 0),
                    "completion_tokens": response.usage_metadata.get("output_tokens", 0),
                    "total_tokens": response.usage_metadata.get("total_tokens", 0),
                    "model": self.model
                }
        except Exception:
            pass

_llm_client_cache: Optional[LLMClient] = None

def get_llm_client(model: Optional[str] = None) -> LLMClient:
    global _llm_client_cache
    if _llm_client_cache is None or model:
        _llm_client_cache = LLMClient(model=model)
    return _llm_client_cache
