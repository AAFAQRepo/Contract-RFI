"""
MinIO storage service — upload, download, delete documents.
"""

import io
from datetime import timedelta
from minio.error import S3Error
from core.clients import minio_client
from core.config import get_settings

settings = get_settings()


def upload_document(file_bytes: bytes, object_name: str, content_type: str = "application/pdf") -> str:
    """
    Upload file bytes to MinIO.
    Returns the object_name (path inside bucket).
    """
    minio_client.put_object(
        bucket_name=settings.MINIO_BUCKET,
        object_name=object_name,
        data=io.BytesIO(file_bytes),
        length=len(file_bytes),
        content_type=content_type,
    )
    return object_name


def download_document(object_name: str) -> bytes:
    """
    Download a document from MinIO and return its bytes.
    """
    response = minio_client.get_object(settings.MINIO_BUCKET, object_name)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def delete_document(object_name: str) -> None:
    """Delete a document from MinIO."""
    try:
        minio_client.remove_object(settings.MINIO_BUCKET, object_name)
    except S3Error:
        pass


def build_object_name(user_id: str, document_id: str, filename: str) -> str:
    """Build a consistent MinIO object path."""
    return f"{user_id}/{document_id}/{filename}"


def get_presigned_upload_url(object_name: str, expires_minutes: int = 10) -> str:
    """
    Generate a presigned PUT URL for browser-based upload.
    """
    return minio_client.presigned_put_object(
        bucket_name=settings.MINIO_BUCKET,
        object_name=object_name,
        expires=timedelta(minutes=expires_minutes),
    )

