"""Bounded registry rotation, including explicit tail batches."""


def select_symbols(issuers, offset, limit=25):
    if type(limit) is not int or not 1 <= limit <= 25:
        raise ValueError("limit must be 1..25")
    if not issuers:
        return [], 0
    if type(offset) is not int or offset < 0:
        raise ValueError("invalid offset")
    start = offset % len(issuers)
    end = min(start + limit, len(issuers))
    return list(issuers[start:end]), 0 if end == len(issuers) else end
