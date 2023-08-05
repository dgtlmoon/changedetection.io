from dataclasses import dataclass, field
from typing import Any

# So that we can queue some metadata in `item`
# https://docs.python.org/3/library/queue.html#queue.PriorityQueue
#
@dataclass(order=True)
class PrioritizedItem:
    priority: int
    item: Any=field(compare=False)
