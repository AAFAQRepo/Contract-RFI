"""
Migration script to update embedding models.
1. Drops the old Qdrant collection ('text_chunks') which used dimension 1024
2. Re-creates the collection with dimension 768
3. Queues all previously parsed documents for re-processing in Celery.
"""
import os
import sys

# Add parent dir to path to import backend modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.clients import qdrant_client, QDRANT_COLLECTION, init_qdrant
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models.models import Document
from core.config import get_settings
from workers.celery_app import process_document

def run_migration():
    print(f"🗑️ Dropping old Qdrant Collection: {QDRANT_COLLECTION}")
    try:
        qdrant_client.delete_collection(QDRANT_COLLECTION)
        print("✅ Drop successful.")
    except Exception as e:
        print(f"⚠️ Could not delete collection (maybe it doesn't exist?): {e}")

    print(f"✨ Re-initializing collection...")
    init_qdrant()

    settings = get_settings()
    engine = create_engine(settings.DATABASE_URL_SYNC)
    Session = sessionmaker(bind=engine)
    session = Session()

    docs = session.query(Document).filter_by(status="ready").all()
    count = len(docs)
    print(f"🔍 Found {count} 'ready' documents to re-process.")

    for doc in docs:
        doc.status = "pending"
        print(f"🔄 Queuing Document #{doc.id} ({doc.filename})...")
        process_document.delay(str(doc.id), str(doc.user_id), doc.object_name, doc.filename)

    session.commit()
    session.close()
    
    print("✅ Migration complete. Celery workers will begin downloading Alibaba-GTE and rebuilding the 768d vectors automatically.")

if __name__ == "__main__":
    run_migration()
