"""
Contract review endpoints — structured risk analysis.
Stubs for Phase 1A — full implementation in Phase 1E.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db

router = APIRouter()


@router.get("/{doc_id}")
async def get_review(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get contract review results (clauses, risks, missing clauses)."""
    # Phase 1E: Fetch structured review from DB
    return {
        "document_id": doc_id,
        "summary": None,
        "overall_risk": None,
        "clauses": [],
        "missing_clauses": [],
        "parties": [],
        "message": "Review endpoint ready — implementation in Phase 1E",
    }
