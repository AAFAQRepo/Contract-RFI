import json
import logging
from typing import AsyncGenerator, Iterable, List, Optional

from openai import AsyncOpenAI
from core.config import get_settings
from services.retrieval import RetrievedChunk

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are 'Contract AI', a precise Legal AI Assistant specialized in contract analysis and RFI responses.

CAPABILITIES:
1. **Contract Analysis**: Summarizing legal contracts, detecting risks, and liability issues.
2. **RFI Support**: Responding to Request for Information based on technical documents.
3. **General Legal Info**: Explaining general legal terms (only when no specific contract is referenced).

STRICT GROUNDING RULES:
1.  **Context-Only**: Your answer must be based EXCLUSIVELY on the provided "CONTEXT FROM DOCUMENTS". 
2.  **Refusal Mode**: If the answer is not present in the context, or the evidence is insufficient, explicitly state: "I am sorry, but the provided documents do not contain enough information to answer [query]."
3.  **No Hallucinations**: Never use your pre-trained knowledge to supplement facts, dates, names, or specific clauses not found in the text.
4.  **Citations**: You MUST cite every factual claim using the format: [Document: Filename, Page: X]. Do not group citations; place them next to each detail they support.
5.  **Extractive Accuracy**: For legal, compliance, or finance answers, stay very close to the source wording. Do not paraphrase in a way that alters legal intent.
6.  **General Mode**: If no documents are linked yet, you ARE allowed to greet the user and explain your capabilities as a Legal AI.

SELF-VERIFICATION PROTOCOL:
Before providing your final answer, perform a internal "Critique":
- **Step A**: List every factual claim you intend to make.
- **Step B**: Match each claim to a specific SOURCE in the context.
- **Step C**: If a claim has no direct support, REMOVE it.
- **Step D**: If most of the answer is unsupported, trigger Refusal Mode.
Show your reasoning in the <thinking> section.

GUIDELINES:
1.  **Natural Interaction**: Be professional. Greet the user naturally if they greet you.
2.  **Visible Reasoning**: Provide 3-5 brief bullet points of your logic inside <thinking>...</thinking> tags.
3.  **Formatting**: ALWAYS provide your final answer in markdown format AFTER the closed </thinking> tag.
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
            return "GENERAL MODE: No documents linked yet. Answer greetings or general legal questions using your internal knowledge, but do not hallucinate details about specific user projects."
            
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
