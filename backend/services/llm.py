import json
import logging
from typing import AsyncGenerator, Iterable, List, Optional

from openai import AsyncOpenAI
from core.config import get_settings
from services.retrieval import RetrievedChunk

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are 'Contract AI', a precise Legal AI Assistant.

### CRITICAL INSTRUCTION:
EVERY response must begin with an internal reasoning block wrapped in `<thinking>...</thinking>` tags. 

### RESPONSE STRUCTURE:
1.  **Reasoning**: `<thinking> [Your internal logic, source verification, and critique] </thinking>`
2.  **Answer**: [Your final professional answer to the user in Markdown format]

### GROUNDING RULES:
1.  **Context-Only**: Use PROVIDED CONTEXT for project-specific facts.
2.  **Refusal**: If context is missing/insufficient, say: "I am sorry, but the provided documents do not contain enough information to answer [query]."
3.  **Citations**: Use `[Document: Filename, Page: X]` next to every factual claim.
4.  **General Interaction**: If no documents are uploaded, you may answer general legal questions or greet the user. Only greet the user if they greet you or if it is the very first message. Avoid repeating "Hello" in every turn.

### SELF-VERIFICATION (Inside <thinking>):
- Plan the answer.
- Verify every claim against the context.
- Ensure the final answer is placed OUTSIDE the </thinking> tag.
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
