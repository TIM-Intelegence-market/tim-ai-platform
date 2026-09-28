"""Offline event-processing replay; not an arbitrary-code reproduction sandbox."""
import hashlib
import json

from src.bugfixer.processing import Event, classify, fingerprint, timestamp
from src.bugfixer.safety import Policy


def replay(events: list[Event], *, cutoff: str, policy: Policy = Policy()) -> dict:
    policy.verify()
    cutoff = timestamp(cutoff)
    previous = None
    result = []
    for event in events:
        if event.timestamp > cutoff:
            raise ValueError('event beyond historical cutoff')
        if previous is not None and event.timestamp < previous:
            raise ValueError('out-of-order replay input')
        previous = event.timestamp
        category = classify(event)
        result.append({'fingerprint': fingerprint(event), 'timestamp': event.timestamp,
                       'category': category.category, 'matched_rule': category.matched_rule})
    canonical = json.dumps(result, sort_keys=True, separators=(',', ':'))
    return {'schema_version': 1, 'cutoff': cutoff, 'events': result,
            'output_hash': hashlib.sha256(canonical.encode()).hexdigest(),
            'scope': 'sanitized_event_processing_only', 'production_bug_reproduced': False}
