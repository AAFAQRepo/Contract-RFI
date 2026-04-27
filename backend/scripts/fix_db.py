import os
from sqlalchemy import create_engine, text

# Try common ports
ports = [5432, 5435]
db_name = "contract_rfi"
user = "admin"
pw = "changeme"

for port in ports:
    url = f"postgresql://{user}:{pw}@127.0.0.1:{port}/{db_name}"
    print(f"Trying {url}...")
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            print(f"✅ Success on port {port}!")
            
            # Now let's try to add the missing columns
            print("Adding 'chunk_index' to 'chunks'...")
            conn.execute(text("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS chunk_index INTEGER;"))
            
            print("Adding 'thinking' to 'chats'...")
            conn.execute(text("ALTER TABLE chats ADD COLUMN IF NOT EXISTS thinking TEXT;"))
            
            conn.commit()
            print("🎉 Database schema updated successfully!")
            break
    except Exception as e:
        print(f"❌ Failed on port {port}: {e}")
