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

AUDITOR_PROMPT = """You are the 'Legal Auditor'. Your job is to verify the accuracy of a draft AI response against the provided context.

### TASK:
Review the DRAFT ANSWER and compare it to the CONTEXT FROM DOCUMENTS. Identify any:
1. **Hallucinations**: Facts not present in the context.
2. **Citation Errors**: Wrong page numbers or filenames.
3. **Inaccuracies**: Misinterpretations of the source text.

### FORMAT:
If the answer is 100% accurate, return: "PASSED".
If there are errors, return a list of CORRECTIONS starting with "FIX:".
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
                temperature=0.1,
                max_tokens=2048,
            )

            async for chunk in stream:
                token = chunk.choices[0].delta.content
                if token:
                    yield token

        except Exception as e:
            logger.error(f"Error calling LLM: {e}")
            yield f"\n\n[System Error: Connection to GPU server failed - {str(e)}]"

    async def verify_and_correct_response(
        self,
        query: str,
        chunks: List[RetrievedChunk],
        draft_answer: str
    ) -> Optional[str]:
        """
        Agentic Step: Audits a draft response and returns a corrected version if needed.
        """
        context_text = self._format_context(chunks)
        audit_content = f"CONTEXT:\n{context_text}\n\nQUERY:\n{query}\n\nDRAFT ANSWER:\n{draft_answer}"

        try:
            # 1. Audit Phase
            audit_res = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": AUDITOR_PROMPT},
                    {"role": "user", "content": audit_content},
                ],
                temperature=0.0,
            )
            report = audit_res.choices[0].message.content or ""

            if "PASSED" in report.upper() and "FIX:" not in report.upper():
                return None # No correction needed

            # 2. Correction Phase
            print(f"🕵️ Auditor found issues: {report[:100]}...")
            correction_prompt = (
                f"{SYSTEM_PROMPT}\n\n"
                f"### AUDITOR REPORT:\n{report}\n\n"
                f"Please provide the final, corrected version of the answer based on the report above. "
                f"Maintain pure rephrasing and strict grounding."
            )
            
            corrected_res = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": correction_prompt},
                    {"role": "user", "content": f"CONTEXT:\n{context_text}\n\nQUERY:\n{query}"},
                ],
                temperature=0.0,
            )
            return corrected_res.choices[0].message.content

        except Exception as e:
            logger.error(f"Auditor failed: {e}")
            return None

    async def generate_thought_and_answer(
        self,
        query: str,
        chunks: List[RetrievedChunk],
        user_name: str = "User"
    ) -> dict:
        """
        Non-streaming version with Agentic Verification built-in.
        """
        # 1. Generate Draft
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
                temperature=0.1,
                max_tokens=2048,
            )
            
            full_text = response.choices[0].message.content or ""
            
            # 2. Verify and Correct
            thinking = ""
            answer = full_text
            
            if "<thinking>" in full_text and "</thinking>" in full_text:
                parts = full_text.split("</thinking>", 1)
                thinking = parts[0].replace("<thinking>", "").strip()
                answer = parts[1].strip()

            # Agentic Loop
            if chunks:
                corrected = await self.verify_and_correct_response(query, chunks, answer)
                if corrected:
                    answer = corrected
            
            return {"thinking": thinking, "answer": answer}

        except Exception as e:
            logger.error(f"Error calling LLM: {e}")
            return {"thinking": "", "answer": "I'm sorry, I'm having trouble connecting to my engine."}
