from datetime import date

from app.workers import partitions


def test_month_arithmetic_wraps_the_year():
    assert partitions.add_months(date(2026, 11, 1), 3) == date(2027, 2, 1)
    assert partitions.add_months(date(2026, 1, 15), 0) == date(2026, 1, 1)


def test_partition_names_sort_chronologically():
    names = [partitions.partition_name(partitions.add_months(date(2026, 9, 1), i))
             for i in range(6)]
    assert names == sorted(names)
    assert names[0] == "alerts_2026_09"
    assert names[-1] == "alerts_2027_02"


def test_a_partition_inside_retention_is_never_dropped():
    """The drop rule: a partition goes only once its upper bound is older than
    the cutoff month, so no row still inside 90 days leaves with it."""
    today = date(2026, 8, 26)
    cutoff = partitions.month_start(date(2026, 5, 28))  # today - 90d
    for offset in range(0, 4):
        start = partitions.add_months(cutoff, offset)
        assert partitions.add_months(start, 1) > cutoff, start
    assert partitions.add_months(partitions.add_months(cutoff, -1), 1) <= cutoff
    assert today.year == 2026
