from app.database.session import engine
from sqlalchemy import text

def migrate():
    with engine.connect() as conn:
        try:
            # Add columns if they don't exist
            conn.execute(text("ALTER TABLE queries ADD COLUMN IF NOT EXISTS recent_count FLOAT NOT NULL DEFAULT 0.0;"))
            conn.execute(text("ALTER TABLE queries ADD COLUMN IF NOT EXISTS last_decay_at TIMESTAMPTZ NOT NULL DEFAULT NOW();"))
            
            # Create index for trending score
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_trending_score ON queries ((historical_count + 10.0 * recent_count) DESC);"))
            
            conn.commit()
            print("Migration completed successfully.")
        except Exception as e:
            print(f"Migration failed: {e}")

if __name__ == "__main__":
    migrate()
