from __future__ import annotations

import os
import logging
import asyncio
import importlib
from typing import Optional, Any, Dict, List, Callable, Union
import functools
import json
# Dynamic provider imports handled at runtime via importlib to support tests and fallbacks
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage, ToolMessage
from typing import Iterator
from langchain_core.tools import tool
from core.agents.key_manager import KeyManager


class _ProviderClientWrapper:
    class _Chat:
        class _Completions:
            def __init__(self, client):
                self._client = client

            def create(self, *, model, messages, max_tokens, temperature, **kwargs):
                # Synchronous wrapper for the async chat() method
                try:
                    # Call client's blocking chat
                    content = self._client.chat(messages, max_tokens=max_tokens, temperature=temperature)
                    return type("Resp", (), {"choices": [type("Choice", (), {"message": type("Msg", (), {"content": content})(), "finish_reason": "completed"})()]})()
                except Exception:
                    raise

        def __init__(self, client):
            self.completions = self._Completions(client)

    def __init__(self, client_instance):
        self.chat = self._Chat(client_instance)


class LLMClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        # Backwards-compatible provider list
        self._providers = []
        self._active_index = None

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
        self._providers = []
        self._active_index = None


    def is_available(self) -> bool:
        return bool(self._get_api_key()) and len(self._provider_candidates()) > 0

    def provider(self) -> str:
        c = self._provider_candidates()
        return c[0] if c else "openai"

    def unavailable_reason(self) -> str:
        if not self._get_api_key():
            return "no API key configured"
        return "available"


    def _get_api_key(self, provider: Optional[str] = None) -> Optional[str]:
        # If provider is explicitly requested, return provider-specific key
        if provider == "openrouter":
            key = os.getenv("OPENROUTER_API_KEY", "").strip()
            return key or None
        if provider == "openai":
            if self.api_key:
                return self.api_key
            key = os.getenv("OPENAI_API_KEY", "").strip()
            return key or None
        if provider == "gemini":
            if self.key_manager:
                k = self.key_manager.get_key()
                if k:
                    return k
                self._log.warning("KeyManager returned no keys! Zombie apocalypse?")
            return None

        # Default behavior: return the first available key in order of preference
        if self.api_key:
            return self.api_key
        or_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if or_key:
            return or_key
        oa_key = os.getenv("OPENAI_API_KEY", "").strip()
        if oa_key:
            return oa_key
        if self.key_manager:
            k = self.key_manager.get_key()
            if k:
                return k
        return None


    def _provider_candidates(self) -> List[str]:
        candidates = []
        if self.api_key:
            candidates.append("openai")
        if os.getenv("OPENROUTER_API_KEY", "").strip():
            candidates.append("openrouter")
        if os.getenv("OPENAI_API_KEY", "").strip():
            candidates.append("openai")
        if self.key_manager:
            candidates.append("gemini")
        if not candidates:
            candidates = ["openai"]
        seen = set()
        out = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out

    def _module_for_provider(self, provider: str) -> str:
        if provider == "gemini":
            return "langchain_google_genai"
        return "openai"

    def _instantiate_provider_client(self, provider: str, current_key: Optional[str], max_tokens: int = 256, temperature: float = 0.2):
        module_name = self._module_for_provider(provider)
        module = importlib.import_module(module_name)
        if provider == "gemini":
            if hasattr(module, "ChatGoogleGenerativeAI"):
                ChatGoogleGenerativeAI = getattr(module, "ChatGoogleGenerativeAI")
                return ChatGoogleGenerativeAI(
                    model=self.model,
                    google_api_key=current_key,
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                    convert_system_message_to_human=True,
                ), True
            raise RuntimeError("Gemini module missing ChatGoogleGenerativeAI")
        else:
            if hasattr(module, "OpenAI"):
                OpenAI = getattr(module, "OpenAI")
                if self.base_url:
                    return OpenAI(api_key=current_key, base_url=self.base_url), False
                return OpenAI(api_key=current_key), False
            raise RuntimeError("OpenAI module missing OpenAI class")

    def _extract_content_from_openai_response(self, response: Any) -> Optional[str]:
        try:
            choices = getattr(response, "choices", None)
            if not choices:
                return None
            choice = choices[0]
            msg = getattr(choice, "message", None)
            if msg is not None:
                return getattr(msg, "content", None)
            return getattr(choice, "content", None)
        except Exception:
            return None

    def _capture_usage(self, response: Any):
        try:
            # OpenAI-style usage
            if hasattr(response, "usage"):
                u = response.usage
                self.last_usage = {
                    "prompt_tokens": getattr(u, "prompt_tokens", 0),
                    "completion_tokens": getattr(u, "completion_tokens", 0),
                    "total_tokens": getattr(u, "total_tokens", 0),
                    "model": self.model,
                }
                return
            # LangChain/google-style usage_metadata
            if hasattr(response, "usage_metadata"):
                # usage_metadata may contain Mock objects in tests, attempt to convert
                in_tokens = response.usage_metadata.get("input_tokens", 0)
                out_tokens = response.usage_metadata.get("output_tokens", 0)
                tot = response.usage_metadata.get("total_tokens", (in_tokens or 0) + (out_tokens or 0))
                try:
                    # If mocks are used, they might be callables; call them
                    if callable(in_tokens):
                        in_tokens = in_tokens()
                    if callable(out_tokens):
                        out_tokens = out_tokens()
                    if callable(tot):
                        tot = tot()
                except Exception:
                    pass
                self.last_usage = {
                    "prompt_tokens": int(in_tokens or 0),
                    "completion_tokens": int(out_tokens or 0),
                    "total_tokens": int(tot or 0),
                    "model": self.model,
                }
                return
            # Some providers include usage in a 'usage' or nested response structure
            # Attempt to parse common cases
            r = getattr(response, 'response', None) or {}
            u = getattr(r, 'usage', None) or getattr(r, 'usage_metadata', None)
            if u:
                inp = getattr(u, 'input_tokens', getattr(u, 'prompt_tokens', 0))
                out = getattr(u, 'output_tokens', getattr(u, 'completion_tokens', 0))
                tot = getattr(u, 'total_tokens', (inp or 0) + (out or 0))
                self.last_usage = {
                    'prompt_tokens': int(inp or 0),
                    'completion_tokens': int(out or 0),
                    'total_tokens': int(tot or 0),
                    'model': self.model
                }
        except Exception:
            pass

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

    async def _chat_async(self, messages: List[Dict[str, str]], max_tokens: int = 256, temperature: float = 0.2) -> str:
        retries = 3
        errors = []
        lc_messages = self._convert_messages(messages)
        for provider in self._provider_candidates():
            if not self._get_api_key(provider):
                continue
            for attempt in range(retries):
                current_key = self._get_api_key(provider)
                try:
                    client, is_gemini = self._instantiate_provider_client(provider, current_key, max_tokens=max_tokens, temperature=temperature)
                    if is_gemini:
                        response = await client.ainvoke(lc_messages)
                        self._capture_usage(response)
                        return response.content
                    else:
                        response = client.chat.completions.create(model=self.model, messages=messages, max_tokens=max_tokens, temperature=temperature, stream=False)
                        content = self._extract_content_from_openai_response(response) or ""
                        self._capture_usage(response)
                        return content
                except Exception as e:
                    errors.append(str(e))
                    is_rate_limit = "429" in str(e) or "ResourceExhausted" in str(e)
                    if is_rate_limit and self.key_manager and provider == "gemini":
                        self._log.warning(f"Hit rate limit with key ending in ...{current_key[-4:] if current_key else 'None'}. Rotating.")
                        self.key_manager.report_error(current_key, 429)
                        if attempt < retries - 1:
                            continue
                    self._log.error(f"LLM chat failed for provider {provider}: {e}")
                    break
        raise RuntimeError(f"All LLM providers failed: {errors}")

    def chat(self, messages: List[Dict[str, str]], max_tokens: int = 256, temperature: float = 0.2) -> str:
        """Synchronous wrapper for chat for compatibility with tests and blocking callers."""
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                raise RuntimeError("LLMClient.chat called from running event loop; use async _chat_async instead")
        except RuntimeError:
            # No running loop - safe to call asyncio.run
            return asyncio.run(self._chat_async(messages, max_tokens=max_tokens, temperature=temperature))

    def chat_stream(self, messages: List[Dict[str, Any]], max_tokens: int = 256, temperature: float = 0.2) -> Iterator[str]:
        providers = self._provider_candidates()
        for provider in providers:
            key = self._get_api_key(provider)
            if not key and provider != "gemini":
                continue
            try:
                client, is_gemini = self._instantiate_provider_client(provider, key, max_tokens=max_tokens, temperature=temperature)
                if is_gemini:
                    try:
                        chunks = asyncio.run(self._chat_stream_async(messages, max_tokens=max_tokens, temperature=temperature))
                        return iter(chunks)
                    except Exception:
                        continue
                else:
                    try:
                        events_iter = client.chat.completions.create(model=self.model, messages=messages, max_tokens=max_tokens, temperature=temperature, stream=True)
                    except Exception:
                        # fallback to non-stream create
                        try:
                            return iter([self.chat(messages, max_tokens=max_tokens, temperature=temperature)])
                        except Exception:
                            continue

                    def _gen():
                        last = None
                        for ev in events_iter:
                            try:
                                choices = getattr(ev, "choices", None) or []
                                if choices:
                                    choice = choices[0]
                                    delta = getattr(choice, "delta", None)
                                    if delta and getattr(delta, "content", None):
                                        yield delta.content
                                        continue
                                    msg = getattr(choice, "message", None)
                                    if msg and getattr(msg, "content", None):
                                        yield msg.content
                                        continue
                                last = ev
                            except Exception:
                                continue
                        if last is not None and getattr(last, "usage", None):
                            self._capture_usage(last)

                    return _gen()
            except Exception:
                continue
        # No provider worked - raise
        raise RuntimeError("No LLM provider available for streaming")

    def chat_with_tools(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]], functions_map: Dict[str, Callable[..., Any]], tool_choice: Optional[str] = "auto", max_rounds: int = 3, max_tokens: int = 256, temperature: float = 0.2, trace_id: Optional[str] = None) -> str:
        providers = self._provider_candidates()
        for provider in providers:
            key = self._get_api_key(provider)
            if not key and provider != "gemini":
                continue
            try:
                client, is_gemini = self._instantiate_provider_client(provider, key, max_tokens=max_tokens, temperature=temperature)
                if is_gemini:
                    try:
                        return asyncio.run(self._chat_with_tools_async(messages, tools, functions_map, tool_choice=tool_choice, max_rounds=max_rounds, max_tokens=max_tokens, temperature=temperature, trace_id=trace_id))
                    except Exception:
                        continue
                else:
                    current_messages = list(messages)
                    tools_used = []
                    for _ in range(max_rounds):
                        response = client.chat.completions.create(model=self.model, messages=current_messages, max_tokens=max_tokens, temperature=temperature)
                        self._capture_usage(response)
                        choices = getattr(response, "choices", []) or []
                        if not choices:
                            return ""
                        choice = choices[0]
                        msg = getattr(choice, "message", None)
                        content = None
                        if msg is not None:
                            content = getattr(msg, "content", None)
                            tcalls = getattr(msg, "tool_calls", None)
                        else:
                            content = getattr(choice, "content", None)
                            tcalls = getattr(choice, "tool_calls", None)
                        if not tcalls:
                            return content or ""
                        for call in tcalls:
                            fname = getattr(getattr(call, 'function', call), 'name', None) or getattr(call, 'name', None)
                            fargs_raw = getattr(getattr(call, 'function', call), 'arguments', None) or getattr(call, 'args', None) or "{}"
                            fargs = fargs_raw
                            if isinstance(fargs_raw, str):
                                try:
                                    fargs = json.loads(fargs_raw)
                                except Exception:
                                    fargs = {}
                            if fname:
                                tools_used.append(fname)
                                if fname in functions_map:
                                    func = functions_map[fname]
                                    import inspect
                                    try:
                                        if inspect.iscoroutinefunction(func):
                                            result = asyncio.run(func(**fargs))
                                        else:
                                            result = func(**fargs)
                                    except Exception as e:
                                        result = f"Error executing {fname}: {e}"
                                    tool_content = str(result)
                                else:
                                    tool_content = f"Error: Function {fname} not found"
                                current_messages.append({"role": "tool", "content": tool_content, "tool_call_id": getattr(call, 'id', None), "name": fname})
                    self.last_usage.setdefault('tools_used', tools_used)
                    return "Max tool rounds exceeded"
            except Exception:
                continue
        raise RuntimeError("No LLM provider available for tool-calls")

    def chat_with_tools_stream(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]], functions_map: Dict[str, Callable[..., Any]], max_tokens: int = 256, temperature: float = 0.2) -> Iterator[Dict[str, Any]]:
        providers = self._provider_candidates()
        for provider in providers:
            key = self._get_api_key(provider)
            if not key and provider != "gemini":
                continue
            try:
                client, is_gemini = self._instantiate_provider_client(provider, key, max_tokens=max_tokens, temperature=temperature)
                if is_gemini:
                    try:
                        events = list(asyncio.run(self.chat_with_tools_stream(messages, tools, functions_map, max_tokens=max_tokens, temperature=temperature)))
                        return iter(events)
                    except Exception:
                        continue
                else:
                    events_iter = client.chat.completions.create(model=self.model, messages=messages, max_tokens=max_tokens, temperature=temperature, stream=True)
                    def gen():
                        for ev in events_iter:
                            choices = getattr(ev, 'choices', None) or []
                            if not choices:
                                if getattr(ev, 'usage', None):
                                    usage = ev.usage
                                    yield {"type": "usage", "prompt_tokens": getattr(usage, 'prompt_tokens', 0), "completion_tokens": getattr(usage, 'completion_tokens', 0), "total_tokens": getattr(usage, 'total_tokens', 0)}
                                continue
                            choice = choices[0]
                            delta = getattr(choice, 'delta', None)
                            if delta and getattr(delta, 'content', None):
                                yield {"type": "delta", "text": delta.content}
                                continue
                            msg = getattr(choice, 'message', None)
                            if msg and getattr(msg, 'content', None):
                                yield {"type": "delta", "text": msg.content}
                                continue
                    return gen()
            except Exception:
                continue
        raise RuntimeError("No LLM provider available for streaming tool-calls")


    async def _chat_stream_async(
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

    async def _chat_with_tools_async(

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
        # Build provider list matching old tests
        provider_wrapper = {
            "name": _llm_client_cache.provider(),
            "model": _llm_client_cache.model,
            "client": _ProviderClientWrapper(_llm_client_cache)
        }
        try:
            _llm_client_cache._providers = [provider_wrapper]
            _llm_client_cache._active_index = 0
        except Exception:
            pass
    return _llm_client_cache

