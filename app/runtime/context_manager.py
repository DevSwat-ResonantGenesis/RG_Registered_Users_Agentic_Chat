"""
Context Window Manager — token-aware trimming for multi-provider LLM calls.
Standalone module, no external service dependencies.
"""

import json
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

try:
    import tiktoken
    _TIKTOKEN = True
except ImportError:
    _TIKTOKEN = False

MODEL_LIMITS = {
    "gpt-4o": 120_000, "gpt-4o-mini": 120_000, "gpt-4-turbo": 120_000,
    "claude-sonnet-4-20250514": 190_000, "claude-3-5-sonnet-20241022": 190_000,
    "llama-3.3-70b-versatile": 120_000, "llama-3.1-8b-instant": 120_000,
    "gemini-2.0-flash": 1_000_000,
}
OUTPUT_RESERVE = 4096
DEFAULT_LIMIT = 120_000


class ContextWindowManager:
    def __init__(self, model: str):
        self.model = model
        self.max_tokens = MODEL_LIMITS.get(model, DEFAULT_LIMIT) - OUTPUT_RESERVE
        self._enc = None
        if _TIKTOKEN:
            try:
                self._enc = tiktoken.encoding_for_model(model)
            except KeyError:
                try:
                    self._enc = tiktoken.get_encoding("cl100k_base")
                except Exception:
                    pass

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        if self._enc:
            try:
                return len(self._enc.encode(text))
            except Exception:
                pass
        return len(text) // 4

    def count_message_tokens(self, msg: Dict) -> int:
        content = msg.get("content", "")
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    parts.append(block.get("text", "") or json.dumps(block.get("input", {})))
                else:
                    parts.append(str(block))
            content = " ".join(parts)
        elif content is None:
            content = ""
        return self.count_tokens(str(content)) + 4

    def total_tokens(self, messages: List[Dict]) -> int:
        return sum(self.count_message_tokens(m) for m in messages)

    def fits(self, messages: List[Dict], tools_tokens: int = 0) -> bool:
        return self.total_tokens(messages) + tools_tokens < self.max_tokens

    def trim_to_fit(self, messages: List[Dict], tools_tokens: int = 0) -> List[Dict]:
        if self.fits(messages, tools_tokens):
            return list(messages)
        budget = self.max_tokens - tools_tokens
        result = [dict(m) for m in messages]

        # Phase 1: Truncate long tool results
        for i, msg in enumerate(result):
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 2000:
                if msg.get("role") in ("tool", "function") or "Tool result" in content[:50]:
                    result[i] = {**msg, "content": content[:2000] + "\n...(truncated)"}
        if self.total_tokens(result) + tools_tokens <= budget:
            return result

        # Phase 2: Compress old turns
        system = result[0] if result and result[0].get("role") == "system" else None
        rest = result[1:] if system else result
        keep_recent = 6
        if len(rest) > keep_recent:
            old = rest[:-keep_recent]
            recent = rest[-keep_recent:]
            summary_parts = []
            for msg in old:
                role = msg.get("role", "unknown")
                c = str(msg.get("content", ""))[:200].replace("\n", " ")
                if role == "user":
                    summary_parts.append(f"User: {c}")
                elif role == "assistant":
                    summary_parts.append(f"Assistant: {c}")
                elif role in ("tool", "function"):
                    summary_parts.append(f"Tool: {c[:100]}")
            compressed = {"role": "user", "content": f"[COMPRESSED HISTORY — {len(old)} earlier messages]\n" + "\n".join(summary_parts[-10:])}
            candidate = ([system] if system else []) + [compressed] + recent
            if self.total_tokens(candidate) + tools_tokens <= budget:
                return candidate

        # Phase 3: Drop oldest non-system messages
        result = list(messages)
        while len(result) > 2 and self.total_tokens(result) + tools_tokens > budget:
            result.pop(1)
        return result

    def estimate_tools_tokens(self, tools: List[Dict]) -> int:
        if not tools:
            return 0
        return self.count_tokens(json.dumps(tools))
