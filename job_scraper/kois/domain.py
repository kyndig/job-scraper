from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class RawIngestionItem:
    source_type: str
    source_name: str
    external_id: str
    raw_body: str
    metadata: dict = field(default_factory=dict)
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
