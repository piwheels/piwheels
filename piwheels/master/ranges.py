def consolidate(ranges):
    """
    Given a list of *ranges* in ascending order, this generator function returns
    the list with any overlapping ranges consolidated into individual ranges.
    For example::

        >>> list(consolidate([range(0, 5), range(4, 10)]))
        [range(0, 10)]
        >>> list(consolidate([range(0, 5), range(5, 10)]))
        [range(0, 10)]
        >>> list(consolidate([range(0, 5), range(6, 10)]))
        [range(0, 5), range(6, 10)]
    """
    start = stop = None
    for r in ranges:
        if start is None:
            start = r.start
        elif r.start > stop:
            yield range(start, stop)
            start = r.start
        stop = r.stop
    yield range(start, stop)


def split(ranges, i):
    """
    Given a list of non-overlapping *ranges* in ascending order, this generator
    function returns the list with the range containing *i* split into two
    ranges, one ending at *i* and the other starting at *i*. If *i* is not
    contained in any of the ranges, then *ranges* is returned unchanged. For
    example::

        >>> list(split([range(10)], 5))
        [range(0, 5), range(5, 10)]
        >>> list(split([range(10)], 0))
        [range(0, 10)]
        >>> list(split([range(10)], 20))
        [range(0, 10)]
    """
    for r in ranges:
        if i in r and i > r.start:
            yield range(r.start, i)
            yield range(i, r.stop)
        else:
            yield r


def exclude(ranges, ex):
    """
    Given a list of non-overlapping *ranges* in ascending order, and a range
    *ex* to exclude, this generator function returns *ranges* with all values
    covered by *ex* removed from any contained ranges. For example::

        >>> list(exclude([range(10)], range(2)))
        [range(2, 10)]
        >>> list(exclude([range(10)], range(2, 4)))
        [range(0, 2), range(4, 10)]
    """
    for r in split(split(ranges, ex.start), ex.stop):
        if r.stop <= ex.start or r.start >= ex.stop:
            yield r


def intersect(r1, r2):
    """
    Returns two ranges *r1* and *r2* (which must both have a step of 1), returns
    the range formed by the intersection of the two ranges, or ``None`` if the
    ranges do not overlap. For example::

        >>> intersect(range(10), range(5))
        range(0, 5)
        >>> intersect(range(10), range(10, 2))
        >>> intersect(range(10), range(2, 5))
        range(2, 5)
    """
    assert r1.step == 1
    assert r2.step == 1
    r = range(max(r1.start, r2.start), min(r1.stop, r2.stop))
    if r:
        return r

