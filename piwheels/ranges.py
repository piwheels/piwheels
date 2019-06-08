# The piwheels project
#   Copyright (c) 2017 Ben Nuttall <https://github.com/bennuttall>
#   Copyright (c) 2017 Dave Jones <dave@waveform.org.uk>
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the copyright holder nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

"""
A set of utility routines for efficiently tracking byte ranges within a stream.
These are used to track which chunks of a file have been received during file
transfers from build slaves.

See :class:`~.file_juggler.FileJuggler` for the usage of these functions.


.. autofunction:: consolidate

.. autofunction:: exclude

.. autofunction:: intersect

.. autofunction:: split
"""


def consolidate(ranges):
    """
    Given a list of *ranges* in ascending order, this generator function
    returns the list with any overlapping ranges consolidated into individual
    ranges. For example::

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


def intersect(range1, range2):
    """
    Given two ranges *range1* and *range2* (which must both have a step of
    1), returns the range formed by the intersection of the two ranges, or
    ``None`` if the ranges do not overlap. For example::

        >>> intersect(range(10), range(5))
        range(0, 5)
        >>> intersect(range(10), range(10, 2))
        >>> intersect(range(10), range(2, 5))
        range(2, 5)
    """
    assert range1.step == 1
    assert range2.step == 1
    r = range(max(range1.start, range2.start), min(range1.stop, range2.stop))
    if r:
        return r
