import logging
import asyncio
from typing import List, Optional
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy

from core.config import get_settings
from services.retrieval import RetrievedChunk

logger = logging.getLogger(__name__)

class EvaluationService:
    def __init__(self):
        settings = get_settings()
        # Configure Ragas to use your local SGLang endpoint as the judge
        # This keeps all evaluation private and free.
        from langchain_openai import ChatOpenAI
        
        self.judge_llm = ChatOpenAI(
            model=settings.SGLANG_INTENT_MODEL,
            openai_api_key=settings.SGLANG_API_KEY,
            openai_api_base=settings.SGLANG_BASE_URL,
            temperature=0
        )
        
        # We also need embeddings for Relevancy (usually)
        # We can use the same endpoint or a placeholder if we stick to non-embedding metrics
        self.metrics = [faithfulness, answer_relevancy]

    async def evaluate_interaction(
        self,
        query: str,
        answer: str,
        chunks: List[RetrievedChunk]
    ) -> dict:
        """
        Run Ragas evaluation on a single chat interaction.
        Returns a dict with scores.
        """
        try:
            # Prepare the dataset for Ragas
            # Ragas expects: question, answer, contexts
            data = {
                "question": [query],
                "answer": [answer],
                "contexts": [[c.text for c in chunks]],
            }
            
            dataset = Dataset.from_dict(data)
            
            # Run evaluation
            # Note: evaluate is normally synchronous, we run it in a thread to keep it async
            result = await asyncio.to_thread(
                evaluate,
                dataset=dataset,
                metrics=self.metrics,
                llm=self.judge_llm,
                raise_exceptions=False
            )
            
            scores = {
                "faithfulness": float(result["faithfulness"]),
                "answer_relevancy": float(result["answer_relevancy"])
            }
            
            logger.info(f"📈 Ragas Scores -> Faithfulness: {scores['faithfulness']:.2f}, Relevancy: {scores['answer_relevancy']:.2f}")
            return scores

        except Exception as e:
            logger.error(f"❌ Ragas evaluation failed: {e}")
            return {"faithfulness": 0.0, "answer_relevancy": 0.0}

    async def background_evaluate_and_save(
        self,
        chat_id: str,
        query: str,
        answer: str,
        chunks: List[RetrievedChunk]
    ):
        """
        Perform evaluation in the background and save to DB.
        """
        from core.database import async_session
        from models.models import Chat
        from sqlalchemy import update
        
        scores = await self.evaluate_interaction(query, answer, chunks)
        
        async with async_session() as db:
            await db.execute(
                update(Chat)
                .where(Chat.id == chat_id)
                .values(
                    faithfulness_score=scores["faithfulness"],
                    relevancy_score=scores["answer_relevancy"]
                )
            )
            await db.commit()
            logger.info(f"💾 Saved Ragas scores for chat {chat_id}")
