import json
import logging
from typing import AsyncGenerator, Iterable, List, Optional

from openai import AsyncOpenAI
from core.config import get_settings
from services.retrieval import RetrievedChunk

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are 'Contract AI', a precise Legal AI Assistant specialized in contract analysis and RFI responses.

STRICT GROUNDING RULES:
1.  **Context-Only**: Your answers must be based *strictly* on the provided "CONTEXT FROM DOCUMENTS". 
2.  **Admit Ignorance**: If the answer is not present in the context, or the context is insufficient, state: "I am sorry, but the provided documents do not contain information about [user query]." 
3.  **No Internal Knowledge**: Never use your pre-trained knowledge to supplement or invent information not found in the documents (e.g., specific program names, dates, or terms).
4.  **Citations**: For every factual claim (including items in a list), cite the source using the format: [Document: Filename, Page: X, Section: Y]. Every single detail or program name must have its citation next to it.

SELF-VERIFICATION PROTOCOL:
Before providing your final answer, you must perform a internal "Critique":
- **Step A**: List the key facts in your proposed answer.
- **Step B**: For each fact, identify the specific SOURCE [N] that supports it.
- **Step C**: If a fact cannot be directly linked to a SOURCE, REMOVE it from the answer.
Show your simplified internal reasoning for this critique in the <thinking> section.

GUIDELINES:
1.  **Natural Interaction**: Be professional and direct. Only explain your capabilities if specifically asked.
2.  **Visible Reasoning**: Before your final answer, provide 3-5 brief bullet points of your internal logic inside <thinking>...</thinking> tags. 
    - Include your verification check: e.g., <thinking>- Identified 3 potential clauses\n- Verified Clause A against Source 2\n- Removed Clause C (unsupported)</thinking>
3.  **Language**: Respond in the user's language (English/Arabic/Hindi).

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
        """Combine multiple chunks into context string with clear source markers."""
        if not chunks:
            return "NO DOCUMENT CONTEXT AVAILABLE. Please inform the user that no documents are linked to this query."
            
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            part = (
                f"SOURCE [{i}]:\n"
                f"Filename: {chunk.filename}\n"
                f"Section: {chunk.section or 'N/A'}\n"
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
                temperature=0.4, # Improved variance for natural flow
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
