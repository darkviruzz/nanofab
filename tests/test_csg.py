"""Set operations as pointwise min/max (plan §3.2)."""

from __future__ import annotations

import numpy as np
import pytest

from nanofab_v3.kernel import csg

A = np.array([-2.0, -1.0, 1.0, 3.0], dtype=np.float32)
B = np.array([1.0, -3.0, -1.0, 2.0], dtype=np.float32)


def test_union_is_the_pointwise_minimum() -> None:
    assert np.array_equal(csg.union(A, B), np.minimum(A, B))
    assert np.array_equal(csg.union(A, B, -A), np.minimum(np.minimum(A, B), -A))


def test_intersection_is_the_pointwise_maximum() -> None:
    assert np.array_equal(csg.intersection(A, B), np.maximum(A, B))


def test_difference_removes_the_second_region() -> None:
    """`A \\ B` is inside exactly where A is inside and B is not."""
    difference = csg.difference(A, B)

    assert np.array_equal(difference < 0, (A < 0) & ~(B < 0))
    assert np.array_equal(difference, np.maximum(A, -B))


def test_complement_flips_the_sign() -> None:
    assert np.array_equal(csg.complement(A), -A)


def test_offset_grows_and_shrinks() -> None:
    """The isotropic fast path: one array operation, exact on a distance field."""
    grown = csg.offset(A, 1.5)
    shrunk = csg.offset(A, -1.5)

    assert np.array_equal(grown, A - np.float32(1.5))
    assert np.array_equal(shrunk, A + np.float32(1.5))
    assert np.count_nonzero(grown < 0) > np.count_nonzero(A < 0)


def test_offset_splitting_is_exact() -> None:
    """`1 x 20 nm` and `4 x 5 nm` agree exactly — the measured probe of plan §4.2."""
    once = csg.offset(A, 20.0)
    split = A
    for _ in range(4):
        split = csg.offset(split, 5.0)

    assert np.max(np.abs(once - split)) == 0.0


def test_operations_keep_the_storage_dtype() -> None:
    """Everything stays dense float32 (plan §3.2)."""
    results = (csg.union(A, B), csg.intersection(A, B), csg.difference(A, B), csg.offset(A, 1.0))
    for result in results:
        assert result.dtype == np.float32


def test_operations_are_n_d_generic() -> None:
    """No hard-coded axis pairs: the same code runs on a 3D field."""
    volume = np.arange(24, dtype=np.float32).reshape(2, 3, 4) - 12.0

    assert csg.union(volume, -volume).shape == (2, 3, 4)
    assert np.array_equal(csg.union(volume, -volume), -np.abs(volume))


def test_mismatched_fields_are_rejected() -> None:
    with pytest.raises(ValueError, match="one shape"):
        csg.union(A, np.zeros(7, dtype=np.float32))
    with pytest.raises(ValueError, match="at least one field"):
        csg.union()
