import json
import logging
from typing import AsyncGenerator, Iterable, List, Optional

from openai import AsyncOpenAI
from core.config import get_settings
from services.retrieval import RetrievedChunk

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are 'Contract AI', a high-precision Legal AI Assistant. 

### OBJECTIVE:
Your ONLY task is to REPHRASE and ORGANIZE the retrieved content into a professional answer. Do NOT add any information, analysis, or external knowledge.

### INTERNAL VERIFICATION (MANDATORY):
Every response must begin with an internal reasoning block wrapped in `<thinking>...</thinking>` tags.
- Identify the specific sentences in the context that answer the query.
- Plan how to rephrase them while maintaining 100% factual fidelity.

### GROUNDING & REFUSAL:
1.  **Pure Rephrasing**: Only provide information that is explicitly stated in the "CONTEXT FROM DOCUMENTS". 
2.  **Zero Addition**: Never add your own opinions, creative details, or external facts.
3.  **Refusal**: If the context does not contain the answer, state: "I am sorry, but the provided documents do not contain information to answer [query]."
4.  **Citations**: Use `[Document: Filename, Page: X]` for every claim.

### RESPONSE STRUCTURE:
1. `<thinking> [Internal verification logic] </thinking>`
2. [Direct, professional rephrased response]
"""

USER_PROMPT_TEMPLATE = """USER NAME: {user_name}

CONTEXT FROM DOCUMENTS:
{context_text}

USER QUERY: 
{query}
"""

# ── LLM Service ──────────────────────────────────────────────────────────────

class LLMService:
    def __init__(self):
        settings = get_settings()
        self.client = AsyncOpenAI(
            base_url=settings.SGLANG_BASE_URL,
            api_key=settings.SGLANG_API_KEY,
        )
        self.model = settings.SGLANG_INTENT_MODEL

    def _format_context(self, chunks: List[RetrievedChunk]) -> str:
        """Combine multiple chunks into context string with clear source markers."""
        if not chunks:
            return "GENERAL MODE: No documents linked. Answer greetings or general legal questions only."
            
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            part = (
                f"SOURCE [{i}]:\n"
                f"Filename: {chunk.filename}\n"
                f"Page: {chunk.page}\n"
                f"Content: {chunk.text}\n"
                f"--------------------------"
            )
            context_parts.append(part)
        return "\n".join(context_parts)

    async def generate_response_stream(
        self,
        query: str,
        chunks: List[RetrievedChunk],
        user_name: str = "User"
    ) -> AsyncGenerator[str, None]:
        """
        Generate a token-by-token streaming response.
        """
        context_text = self._format_context(chunks)
        user_content = USER_PROMPT_TEMPLATE.format(
            user_name=user_name,
            context_text=context_text,
            query=query
        )

        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                stream=True,
                temperature=0.1, # Maximum instruction following
                max_tokens=2048,
            )

            async for chunk in stream:
                token = chunk.choices[0].delta.content
                if token:
                    yield token

        except Exception as e:
            logger.error(f"Error calling LLM: {e}")
            yield f"\n\n[System Error: Connection to GPU server failed - {str(e)}]"

    async def generate_thought_and_answer(
        self,
        query: str,
        chunks: List[RetrievedChunk],
        user_name: str = "User"
    ) -> dict:
        """
        Non-streaming legacy version (kept for sync operations).
        Parses reasoning out of <thinking> tags.
        """
        context_text = self._format_context(chunks)
        user_content = USER_PROMPT_TEMPLATE.format(
            user_name=user_name,
            context_text=context_text,
            query=query
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.2,
                max_tokens=2048,
            )
            
            full_text = response.choices[0].message.content or ""
            
            # Simple Tag Parser
            thinking = ""
            answer = full_text
            
            if "<thinking>" in full_text and "</thinking>" in full_text:
                parts = full_text.split("</thinking>", 1)
                thinking = parts[0].replace("<thinking>", "").strip()
                answer = parts[1].strip()
            
            return {"thinking": thinking, "answer": answer}

        except Exception as e:
            logger.error(f"Error calling LLM: {e}")
            return {"thinking": "", "answer": "I'm sorry, I'm having trouble connecting to my engine."}
