import asyncio
from sqlalchemy import text
from core.database import engine

async def check_db():
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='chats';"))
            columns = [row[0] for row in result.fetchall()]
            print(f"COLUMNS: {columns}")
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(check_db())
