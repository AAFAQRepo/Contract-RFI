"""
SQLAlchemy ORM models for all database tables.
"""

import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Text, Integer, BigInteger, Boolean,
    DateTime, ForeignKey, Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    documents = relationship("Document", back_populates="user", cascade="all, delete-orphan")
    chats = relationship("Chat", back_populates="user", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_size_bytes = Column(BigInteger, nullable=True)
    file_type = Column(String, nullable=False)  # pdf, docx
    language = Column(String, nullable=True)     # en, ar, hi, mixed
    contract_type = Column(String, nullable=True)
    status = Column(String, nullable=False, default="uploading")  # uploading, processing, ready, error
    error_message = Column(Text, nullable=True)
    page_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="documents")
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")
    review = relationship("Review", back_populates="document", uselist=False, cascade="all, delete-orphan")
    chats = relationship("Chat", back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_documents_user_id", "user_id"),
        Index("idx_documents_status", "status"),
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_type = Column(String, nullable=False)       # 'retrieval' or 'analysis'
    text = Column(Text, nullable=False)
    context_summary = Column(Text, nullable=True)      # contextual prefix (retrieval chunks)
    section = Column(String, nullable=True)            # e.g. "Article 7"
    clause_type = Column(String, nullable=True)        # e.g. "penalty" (analysis chunks)
    page = Column(Integer, nullable=True)
    language = Column(String, nullable=True)
    token_count = Column(Integer, nullable=True)
    qdrant_point_id = Column(String, nullable=True)    # links to Qdrant vector
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    document = relationship("Document", back_populates="chunks")

    __table_args__ = (
        Index("idx_chunks_document_id", "document_id"),
        Index("idx_chunks_chunk_type", "chunk_type"),
        Index("idx_chunks_clause_type", "clause_type"),
    )


class Review(Base):
    __tablename__ = "reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True)
    summary = Column(Text, nullable=True)
    overall_risk = Column(String, nullable=True)       # high, medium, low
    clauses = Column(JSONB, default=list)               # [{type, text, section, page, risk_level, risk_reason}]
    missing_clauses = Column(JSONB, default=list)       # ["force_majeure", ...]
    parties = Column(JSONB, default=list)               # [{name, role}]
    key_dates = Column(JSONB, default=list)             # [{description, date, section}]
    financial_terms = Column(JSONB, default=list)       # [{description, amount, currency, section}]
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    document = relationship("Document", back_populates="review")


class Chat(Base):
    __tablename__ = "chats"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    query = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    sources = Column(JSONB, default=list)               # [{chunk_id, section, page, text_snippet}]
    intent = Column(String, nullable=True)              # simple_qa, summary, risk
    route = Column(String, nullable=True)               # hybrid_rag, cache, bm25
    latency_ms = Column(Integer, nullable=True)
    cache_hit = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="chats")
    document = relationship("Document", back_populates="chats")

    __table_args__ = (
        Index("idx_chats_user_document", "user_id", "document_id"),
        Index("idx_chats_created_at", "created_at"),
    )


class QueryLog(Base):
    __tablename__ = "query_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    document_id = Column(UUID(as_uuid=True), nullable=True)
    query = Column(Text, nullable=False)
    intent = Column(String, nullable=True)
    route = Column(String, nullable=True)
    retrieved_chunk_ids = Column(JSONB, nullable=True)
    reranked_chunk_ids = Column(JSONB, nullable=True)
    final_answer = Column(Text, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    cache_hit = Column(Boolean, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_query_logs_created_at", "created_at"),
    )


class CacheEntry(Base):
    __tablename__ = "cache_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=True)
    query_text = Column(Text, nullable=False)
    query_hash = Column(String, nullable=False)
    answer = Column(Text, nullable=False)
    sources = Column(JSONB, nullable=True)
    hit_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_cache_document_hash", "document_id", "query_hash"),
    )
