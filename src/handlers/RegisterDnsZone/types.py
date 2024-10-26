from dataclasses import dataclass
from typing import Optional

@dataclass
class EventResourceProperties:
    ZoneName: str
    NameServers: Optional[str]
