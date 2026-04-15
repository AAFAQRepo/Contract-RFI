import json
import logging
from typing import AsyncGenerator, Iterable, List, Optional

from openai import AsyncOpenAI
from core.config import get_settings
from services.retrieval import RetrievedChunk

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are 'Contract AI', an expert Legal AI Assistant specialized in contract analysis and RFI responses.

GUIDELINES:
1.  **Natural Interaction**: Don't be a robot. Only introduce yourself or explain your capabilities if the user is new or specifically asks "What can you do?". Otherwise, be conversational and direct.
2.  **Visible Reasoning**: Before your final answer, provide 3-5 brief bullet points of your internal logic inside <thinking>...</thinking> tags. 
    - Example: <thinking>- Scanning for penalty clauses\n- Comparing Article 4 with Article 9</thinking>
3.  **Strict Legal Context**: Always steer the conversation toward contracts, legal review, or RFI evidence.
4.  **Language**: Respond in the user's language (English/Arabic/Hindi).

FORMATTING:
- Start with <thinking> bullets.
- Follow with your direct, markdown-formatted answer.
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
        """Combine multiple chunks into context string."""
        if not chunks:
            return "NO DOCUMENT CONTEXT (Global/General help mode)."
            
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            score_text = f"Score   : {chunk.score:.2f} (High Confidence)" if hasattr(chunk, "score") and chunk.score else "Score   : N/A"
            part = (
                f"╔══ EVIDENCE [{i}/{len(chunks)}] ═══════════════════════════════════╗\n"
                f"║ File    : {chunk.document_id}\n"
                f"║ Location: {chunk.section} · Page {chunk.page}\n"
                f"║ {score_text}\n"
                f"╚══════════════════════════════════════════════════════╝\n"
                f"Content:\n"
                f"{chunk.text}\n"
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
                temperature=0.4, # Improved variance for natural flow
                max_tokens=2048,
                extra_body={"cache_prompt": True},
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
                extra_body={"cache_prompt": True},
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
