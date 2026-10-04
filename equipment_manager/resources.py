"""Release inactive error frames without losing diagnostic call stacks."""
from __future__ import annotations

import traceback
import builtins


_EXCEPTION_GROUP = getattr(builtins, 'BaseExceptionGroup', ())


def release_error_frames(error: BaseException) -> None:
    """Drop locals held by completed frames in an exception chain.

    Camera/model libraries can leave large image buffers in their error locals.
    Clearing only our caller's image variable does not release those buffers.
    Traceback filenames, line numbers, messages and chaining remain available.
    Python skips frames that are still executing. Cycle protection also handles
    custom exception chains without retaining any errors between calls.
    """
    pending = [error]
    seen = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        traceback.clear_frames(current.__traceback__)
        for linked in (current.__cause__, current.__context__):
            if linked is not None:
                pending.append(linked)
        if isinstance(current, _EXCEPTION_GROUP):
            pending.extend(current.exceptions)
