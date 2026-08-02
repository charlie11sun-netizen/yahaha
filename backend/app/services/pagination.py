def normalize_pagination(limit: int, offset: int, *, max_limit: int = 60) -> tuple[int, int]:
    return max(1, min(int(limit), max_limit)), max(0, int(offset))
