import pytest

from scripts.wiki_article_benchmark import intervals


def test_overlapping_stages_are_reported_separately():
    result = intervals([
        {'stage': 'editor', 'event': 'start', 'at': 10},
        {'stage': 'reviewer', 'event': 'start', 'at': 12},
        {'stage': 'editor', 'event': 'end', 'at': 20},
        {'stage': 'reviewer', 'event': 'end', 'at': 25},
    ])
    assert result['observed_wall_seconds'] == 15
    assert [s['elapsed_seconds'] for s in result['completed']] == [10, 13]
    assert result['open_stages'] == []


@pytest.mark.parametrize('events', [
    [{'stage': 'a', 'event': 'end', 'at': 1}],
    [{'stage': 'a', 'event': 'start', 'at': float('nan')}],
    [{'stage': 'a', 'event': 'start', 'at': 2}, {'stage': 'b', 'event': 'start', 'at': 1}],
    [{'stage': 'a', 'event': 'start', 'at': 1}, {'stage': 'a', 'event': 'start', 'at': 2}],
])
def test_invalid_measurements_fail(events):
    with pytest.raises(ValueError):
        intervals(events)


def test_missing_end_does_not_invent_elapsed_time():
    result = intervals([{'stage': 'reader', 'event': 'start', 'at': 1}])
    assert result['completed'] == []
    assert result['open_stages'] == ['reader']
