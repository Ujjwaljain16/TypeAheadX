from app.database.session import engine
from sqlalchemy import text

def migrate():
    with engine.connect() as conn:
        try:
            # Add columns if they don't exist
            conn.execute(text("ALTER TABLE queries ADD COLUMN IF NOT EXISTS recent_count FLOAT NOT NULL DEFAULT 0.0;"))
            conn.execute(text("ALTER TABLE queries ADD COLUMN IF NOT EXISTS last_decay_at TIMESTAMPTZ NOT NULL DEFAULT NOW();"))
            
            # The expression index on the trending score is never used by the (read-time decayed) ranking
            # and only costs write maintenance, so older databases drop it.
            conn.execute(text("DROP INDEX IF EXISTS idx_trending_score;"))
            
            conn.commit()
            print("Migration completed successfully.")
        except Exception as e:
            print(f"Migration failed: {e}")

if __name__ == "__main__":
    migrate()
