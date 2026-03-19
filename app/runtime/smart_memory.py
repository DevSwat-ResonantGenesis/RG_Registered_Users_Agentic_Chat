"""
Smart Memory Retrieval — scores, filters, deduplicates memories before prompt injection.
Standalone module, no external service dependencies.
"""

import re
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "and", "but", "or", "nor", "not", "so", "yet",
    "both", "either", "neither", "each", "every", "all", "any", "few",
    "more", "most", "other", "some", "such", "no", "only", "own", "same",
    "than", "too", "very", "just", "about", "above", "also", "this",
    "that", "these", "those", "i", "you", "he", "she", "it", "we", "they",
    "me", "him", "her", "us", "them", "my", "your", "his", "its", "our",
    "their", "what", "which", "who", "whom", "when", "where", "why", "how",
    "if", "then", "else", "up", "out", "down", "off", "over", "under",
    "again", "further", "once", "here", "there", "because", "until",
    "while", "between", "against", "without", "within",
})


def _extract_keywords(text: str) -> List[str]:
    words = re.findall(r'\b[a-zA-Z0-9_]+\b', text.lower())
    return [w for w in words if len(w) > 2 and w not in _STOPWORDS]


def _extract_content(mem) -> str:
    if isinstance(mem, dict):
        return mem.get("content", mem.get("text", mem.get("summary", str(mem))))
    return str(mem)


def score_memory_relevance(memory_text: str, query: str, history: Optional[List[Dict]] = None) -> float:
    query_words = set(_extract_keywords(query))
    mem_words = set(_extract_keywords(memory_text))
    if not query_words or not mem_words:
        return 0.05
    intersection = query_words & mem_words
    union = query_words | mem_words
    keyword_score = len(intersection) / max(len(union), 1)
    history_boost = 0.0
    if history:
        recent_text = " ".join(str(m.get("content", ""))[:200] for m in history[-5:] if isinstance(m, dict))
        recent_words = set(_extract_keywords(recent_text))
        if mem_words and recent_words:
            history_boost = min(len(mem_words & recent_words) / max(len(mem_words), 1) * 0.2, 0.2)
    return min(1.0, keyword_score + history_boost)


def _deduplicate(scored: List[Dict], threshold: float = 0.6) -> List[Dict]:
    sorted_mems = sorted(scored, key=lambda x: x["score"], reverse=True)
    result = []
    for mem in sorted_mems:
        mem_words = set(_extract_keywords(mem["content"]))
        is_dup = False
        for existing in result:
            existing_words = set(_extract_keywords(existing["content"]))
            if not mem_words or not existing_words:
                continue
            overlap = len(mem_words & existing_words) / max(len(mem_words | existing_words), 1)
            if overlap > threshold:
                is_dup = True
                break
        if not is_dup:
            result.append(mem)
    return result


def filter_and_rank_memories(memories: list, query: str, history: Optional[List[Dict]] = None,
                             min_score: float = 0.15, max_results: int = 5) -> List[Dict]:
    scored = []
    for mem in memories:
        content = _extract_content(mem)
        if not content or not content.strip():
            continue
        score = score_memory_relevance(content, query, history)
        scored.append({"content": content[:500], "score": score, "raw": mem})
    relevant = [m for m in scored if m["score"] >= min_score]
    deduped = _deduplicate(relevant)
    deduped.sort(key=lambda x: x["score"], reverse=True)
    return deduped[:max_results]


def format_memories_for_prompt(ranked_memories: List[Dict]) -> str:
    if not ranked_memories:
        return ""
    lines = ["RELEVANT MEMORIES FROM PREVIOUS CONVERSATIONS (scored by relevance):"]
    for i, mem in enumerate(ranked_memories, 1):
        score = mem["score"]
        label = "HIGH" if score > 0.5 else "MEDIUM" if score > 0.25 else "LOW"
        content = mem["content"].strip()[:500]
        lines.append(f"  {i}. [{label}] {content}")
    return "\n".join(lines)
