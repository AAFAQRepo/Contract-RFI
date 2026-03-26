import json
import logging
from typing import AsyncGenerator, List, Optional

from openai import AsyncOpenAI
from core.config import get_settings
from services.retrieval import RetrievedChunk

logger = logging.getLogger(__name__)

# ── Prompt Templates ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert Legal AI Assistant specialized in contract analysis and RFI (Request for Information) responses.
Your goal is to provide accurate, concise, and legally-sound answers based strictly on the provided contract context.

GUIDELINES:
1.  **Strict Context Adherence**: Only answer based on the provided document segments. If the information is missing, say "I cannot find this information in the provided documents."
2.  **Verbatim Citations**: When referencing a specific clause or penalty, use direct quotes where possible.
3.  **Citations**: Always mention the document name and page number (e.g., [SLA, Page 4]).
4.  **Reasoning**: Before giving the final answer, perform a brief internal reasoning (thinking) step to identify relevant sections.
5.  **Language**: Respond in the same language as the user's query (Arabic/English/Hindi).

FORMATTING:
- Use markdown for structure (headings, bullet points, bold text).
- Use a clear "Reasoning" block if requested.
"""

USER_PROMPT_TEMPLATE = """CONTEXT FROM DOCUMENTS:
{context_text}

USER QUERY:
{query}

Please provide your response based ONLY on the context above.
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
        """Combine multiple chunks into a single readable context string."""
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            part = (
                f"--- SEGMENT {i} ---\n"
                f"Document: {chunk.document_id}\n"
                f"Section: {chunk.section}\n"
                f"Page: {chunk.page}\n"
                f"Content: {chunk.text}\n"
            )
            context_parts.append(part)
        return "\n".join(context_parts)

    async def generate_response(
        self, 
        query: str, 
        chunks: List[RetrievedChunk]
    ) -> AsyncGenerator[str, None]:
        """
        Generate a streaming response from the LLM.
        Expected to yield chunks of text.
        """
        context_text = self._format_context(chunks)
        user_content = USER_PROMPT_TEMPLATE.format(
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
                temperature=0.1, # Low temperature for legal accuracy
                max_tokens=2048,
            )

            async for chunk in stream:
                content = chunk.choices[0].delta.content
                if content:
                    yield content

        except Exception as e:
            logger.error(f"Error calling LLM: {e}")
            yield f"Error: I encountered a problem communicating with the LLM server on the GPU machine. ({str(e)})"

    async def generate_thought_and_answer(
        self,
        query: str,
        chunks: List[RetrievedChunk]
    ) -> dict:
        """
        Non-streaming version that returns thinking + final answer.
        This is useful for the current UI which expects a 'thinking' block followed by 'text'.
        """
        context_text = self._format_context(chunks)
        user_content = USER_PROMPT_TEMPLATE.format(
            context_text=context_text,
            query=query
        )

        try:
            # Note: Llama 3.1 8B might not have a native 'thinking' block like DeepSeek, 
            # so we prompt it to reason first. We can then split the response.
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.1,
                max_tokens=2048,
            )
            
            full_text = response.choices[0].message.content or ""
            
            # Simple heuristic: if the model starts with 'Reasoning:' or 'Thinking:', we split.
            # Otherwise we return the whole thing.
            thinking = ""
            answer = full_text
            
            if "Reasoning:" in full_text:
                parts = full_text.split("Reasoning:", 1)[1].split("\n\n", 1)
                if len(parts) > 1:
                    thinking = parts[0].strip()
                    answer = parts[1].strip()
            
            return {
                "thinking": thinking,
                "answer": answer
            }

        except Exception as e:
            logger.error(f"Error calling LLM: {e}")
            return {
                "thinking": "Attempted to connect to GPU server...",
                "answer": f"Connection Failure: Could not reach Llama 3.1 8B at {self.client.base_url}. Please ensure the server is running."
            }
