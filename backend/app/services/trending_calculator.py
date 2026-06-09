from dataclasses import dataclass
import math
from typing import Dict, List
from datetime import datetime, timezone

@dataclass
class QueryState:
    query: str
    historical_count: int
    recent_count: float
    last_decay_at: datetime

@dataclass
class DecayedUpdate:
    query: str
    delta: int
    historical_count: int
    new_recent_count: float
    last_decay_at: datetime

class TrendingCalculator:
    def __init__(self, decay_lambda: float = 0.5):
        self.decay_lambda = decay_lambda

    def compute_decayed_updates(
        self, 
        snapshot: Dict[str, int], 
        db_rows: List[QueryState]
    ) -> List[DecayedUpdate]:
        """
        Takes the buffer snapshot and the current DB rows for those queries,
        and computes the new trending signals with exponential decay applied.
        """
        now = datetime.now(timezone.utc)
        updates = []
        
        # Build lookup for existing rows
        db_lookup = {row.query: row for row in db_rows}
        
        for query, delta in snapshot.items():
            if query in db_lookup:
                row = db_lookup[query]
                historical_count = row.historical_count + delta
                
                # Calculate hours elapsed since last decay
                # Ensure we handle naive datetimes if SQLAlchemy returns them
                last_decay = row.last_decay_at
                if last_decay.tzinfo is None:
                    last_decay = last_decay.replace(tzinfo=timezone.utc)
                
                delta_time = now - last_decay
                hours_elapsed = delta_time.total_seconds() / 3600.0
                
                # Exponential decay formula: new = old * e^(-lambda * hours) + delta
                new_recent_count = row.recent_count * math.exp(-self.decay_lambda * hours_elapsed) + delta
                
                updates.append(DecayedUpdate(
                    query=query,
                    delta=delta,
                    historical_count=historical_count,
                    new_recent_count=new_recent_count,
                    last_decay_at=now
                ))
            else:
                # New query
                updates.append(DecayedUpdate(
                    query=query,
                    delta=delta,
                    historical_count=delta,
                    new_recent_count=float(delta),
                    last_decay_at=now
                ))
                
        return updates
