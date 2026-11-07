"""Short-lived, bounded owner discovery cache; never used for signing plans."""
from collections import OrderedDict
from copy import deepcopy
from time import monotonic


class ClaimDiscoveryCache:
    def __init__(self, *, max_entries=128, ttl_seconds=10):
        self.max_entries, self.ttl_seconds = max_entries, ttl_seconds
        self.entries = OrderedDict()

    def clear(self):
        self.entries.clear()

    def get(self, key):
        entry = self.entries.get(key)
        if entry is None:
            return None
        expires, value = entry
        if expires <= monotonic():
            del self.entries[key]
            return None
        self.entries.move_to_end(key)
        return deepcopy(value)

    def put(self, key, value):
        now = monotonic()
        for old, (expires, _) in list(self.entries.items()):
            if expires <= now:
                del self.entries[old]
        self.entries[key] = (now + self.ttl_seconds, deepcopy(value))
        self.entries.move_to_end(key)
        while len(self.entries) > self.max_entries:
            self.entries.popitem(last=False)

    def invalidate_owner(self, wallet):
        for key in list(self.entries):
            if key[0] == wallet:
                del self.entries[key]
