"""Long-range matching cannot starve missing views or repeat known pairs."""
import numpy as np

from scripts.pilot.route_loop_completion import bounded_pairs, known_pairs


def test_existing_empty_match_row_is_not_reinserted():
    class NativeBoundary:
        def exists_matches(self, first, second):
            return (first, second) in {(1, 2), (1, 3)}

        def read_all_matches(self):
            raise AssertionError('Bulk reads do not include zero-match rows')

    assert known_pairs(NativeBoundary(), [1, 2, 3]) == {(1, 2), (1, 3)}


def test_small_partial_map_gets_every_untried_missing_to_registered_pair():
    ids = [100 + 3*i for i in range(81)]
    registered = set(ids[11:])
    existing = {tuple(sorted((ids[i], ids[j]))) for i in range(81)
                for j in range(i+1, min(i+9, 81))}
    pairs = bounded_pairs(np.ones((81, 81)), ids, registered, existing)
    actual = {(ids[i], ids[j]) for i, j in pairs}
    required = {(ids[i], ids[j]) for i in range(11) for j in range(11, 81)
                if (ids[i], ids[j]) not in existing}
    assert required <= actual
    assert not actual & existing
    assert len(pairs) == len(set(pairs)) <= 1200
    assert all(0 <= i < j < len(ids) for i, j in pairs)


def test_large_partial_map_balances_budget_across_all_missing_views():
    ids = list(range(1, 241))
    similarity = np.random.default_rng(17).random((240, 240))
    registered = set(ids[80:])
    pairs = bounded_pairs(similarity, ids, registered, set())
    assert len(pairs) == 1200
    assert {i for i, j in pairs if ids[i] not in registered} == set(range(80))
    assert all(ids[j] in registered for _, j in pairs)
    assert pairs == bounded_pairs(similarity, ids, registered, set())


def test_complete_map_only_proposes_bounded_new_long_range_pairs():
    ids = list(range(1, 25))
    known = {(1, 20)}
    pairs = bounded_pairs(np.eye(24), ids, set(ids), known)
    assert (0, 19) not in pairs
    assert all(j-i >= 10 for i, j in pairs)
