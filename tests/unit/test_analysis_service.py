"""
Unit tests for app/services/analysis_service.py

Covers:
- detect_spending_outliers: minimum data-point guard, clear upper outlier
- detect_income_outliers: minimum data-point guard, clear lower outlier
- compute_monthly_totals: income/spending split, uncategorized skip,
                          outlier_id exclusion, month sorting, net calculation
- compute_category_spend: outflow-only, month filter, outlier_id skip,
                          descending sort, unknown category skip
- compute_category_averages: basic average, IQR outlier exclusion,
                             raw_average vs adjusted average
"""


from app.services.analysis_service import (
    compute_category_averages,
    compute_category_spend,
    compute_monthly_totals,
    detect_income_outliers,
    detect_spending_outliers,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_tx(tx_id, date, amount, category_id="cat1"):
    return {"id": tx_id, "date": date, "amount": amount, "category_id": category_id}


def make_cat(cat_id, name, group_name="Everyday Expenses"):
    return {"id": cat_id, "name": name, "group_name": group_name}


# ---------------------------------------------------------------------------
# detect_spending_outliers
# ---------------------------------------------------------------------------

class TestDetectSpendingOutliers:
    def test_fewer_than_5_points_returns_empty(self):
        assert detect_spending_outliers([100, 200, 300, 400]) == []

    def test_exactly_5_equal_values_no_outlier(self):
        assert detect_spending_outliers([100, 100, 100, 100, 100]) == []

    def test_clear_upper_outlier_detected(self):
        # Five normal months (~$100) and one wildly high month ($10_000)
        amounts = [100_000, 105_000, 95_000, 110_000, 98_000, 10_000_000]
        outliers = detect_spending_outliers(amounts)
        assert 5 in outliers  # index 5 is the $10,000 spike

    def test_returns_indices_not_values(self):
        amounts = [50, 60, 55, 58, 52, 5000]
        outliers = detect_spending_outliers(amounts)
        assert all(isinstance(i, int) for i in outliers)

    def test_no_outlier_in_normal_spread(self):
        # Graduated but not extreme spread
        amounts = [100_000, 120_000, 90_000, 110_000, 105_000]
        assert detect_spending_outliers(amounts) == []

    def test_empty_list_returns_empty(self):
        assert detect_spending_outliers([]) == []


# ---------------------------------------------------------------------------
# detect_income_outliers
# ---------------------------------------------------------------------------

class TestDetectIncomeOutliers:
    def test_fewer_than_5_points_returns_empty(self):
        assert detect_income_outliers([1000, 2000, 3000]) == []

    def test_clear_lower_outlier_detected(self):
        # Five normal months (~$5,000) and one very low month ($10)
        amounts = [5_000_000, 5_100_000, 4_900_000, 5_050_000, 4_950_000, 10_000]
        outliers = detect_income_outliers(amounts)
        assert 5 in outliers  # index 5 is the near-zero month

    def test_no_outlier_for_symmetric_data(self):
        amounts = [5_000_000, 5_100_000, 4_900_000, 5_050_000, 4_950_000]
        assert detect_income_outliers(amounts) == []

    def test_empty_list_returns_empty(self):
        assert detect_income_outliers([]) == []


# ---------------------------------------------------------------------------
# compute_monthly_totals
# ---------------------------------------------------------------------------

class TestComputeMonthlyTotals:
    def test_basic_income_and_spending(self):
        txns = [
            make_tx("t1", "2024-01-15", 3_000_000),   # income $3,000
            make_tx("t2", "2024-01-20", -1_500_000),  # spending $1,500
        ]
        result = compute_monthly_totals(txns, set())
        assert len(result) == 1
        row = result[0]
        assert row.month == "2024-01"
        assert row.income == 3_000_000
        assert row.spending == 1_500_000
        assert row.net == 1_500_000

    def test_uncategorized_transactions_skipped(self):
        txns = [
            make_tx("t1", "2024-01-15", -500_000, category_id=None),
        ]
        result = compute_monthly_totals(txns, set())
        assert result == []

    def test_outlier_ids_excluded(self):
        txns = [
            make_tx("t1", "2024-01-15", 3_000_000),
            make_tx("t2", "2024-01-20", -1_000_000),
        ]
        result = compute_monthly_totals(txns, outlier_ids={"t1"})
        assert result[0].income == 0
        assert result[0].spending == 1_000_000

    def test_results_sorted_by_month(self):
        txns = [
            make_tx("t1", "2024-03-01", -100_000),
            make_tx("t2", "2024-01-01", -100_000),
            make_tx("t3", "2024-02-01", -100_000),
        ]
        result = compute_monthly_totals(txns, set())
        months = [r.month for r in result]
        assert months == ["2024-01", "2024-02", "2024-03"]

    def test_multiple_transactions_same_month_aggregated(self):
        txns = [
            make_tx("t1", "2024-01-01", -200_000),
            make_tx("t2", "2024-01-15", -300_000),
            make_tx("t3", "2024-01-28", -100_000),
        ]
        result = compute_monthly_totals(txns, set())
        assert result[0].spending == 600_000

    def test_net_is_income_minus_spending(self):
        txns = [
            make_tx("t1", "2024-01-01", 2_000_000),
            make_tx("t2", "2024-01-15", -800_000),
        ]
        result = compute_monthly_totals(txns, set())
        assert result[0].net == 2_000_000 - 800_000

    def test_empty_transactions_returns_empty(self):
        assert compute_monthly_totals([], set()) == []


# ---------------------------------------------------------------------------
# compute_category_spend
# ---------------------------------------------------------------------------

class TestComputeCategorySpend:
    def test_only_outflows_included(self):
        cats = [make_cat("cat1", "Groceries")]
        txns = [
            make_tx("t1", "2024-01-10", -500_000),   # outflow — included
            make_tx("t2", "2024-01-15", 1_000_000),  # income — excluded
        ]
        result = compute_category_spend(txns, cats, "2024-01", set())
        assert len(result) == 1
        assert result[0]["amount"] == 500_000

    def test_month_filter(self):
        cats = [make_cat("cat1", "Groceries")]
        txns = [
            make_tx("t1", "2024-01-10", -500_000),
            make_tx("t2", "2024-02-10", -800_000),  # different month
        ]
        result = compute_category_spend(txns, cats, "2024-01", set())
        assert len(result) == 1
        assert result[0]["amount"] == 500_000

    def test_outlier_ids_excluded(self):
        cats = [make_cat("cat1", "Groceries")]
        txns = [
            make_tx("t1", "2024-01-10", -500_000),
            make_tx("t2", "2024-01-20", -200_000),
        ]
        result = compute_category_spend(txns, cats, "2024-01", outlier_ids={"t1"})
        assert result[0]["amount"] == 200_000

    def test_unknown_category_skipped(self):
        cats = [make_cat("cat1", "Groceries")]
        txns = [
            make_tx("t1", "2024-01-10", -500_000, category_id="unknown-cat"),
        ]
        result = compute_category_spend(txns, cats, "2024-01", set())
        assert result == []

    def test_sorted_descending_by_amount(self):
        cats = [
            make_cat("cat1", "Dining"),
            make_cat("cat2", "Groceries"),
            make_cat("cat3", "Transport"),
        ]
        txns = [
            make_tx("t1", "2024-01-01", -300_000, "cat1"),
            make_tx("t2", "2024-01-02", -100_000, "cat3"),
            make_tx("t3", "2024-01-03", -500_000, "cat2"),
        ]
        result = compute_category_spend(txns, cats, "2024-01", set())
        amounts = [r["amount"] for r in result]
        assert amounts == sorted(amounts, reverse=True)

    def test_uncategorized_transactions_skipped(self):
        cats = [make_cat("cat1", "Groceries")]
        txns = [
            make_tx("t1", "2024-01-10", -500_000, category_id=None),
        ]
        result = compute_category_spend(txns, cats, "2024-01", set())
        assert result == []

    def test_empty_transactions_returns_empty(self):
        cats = [make_cat("cat1", "Groceries")]
        result = compute_category_spend([], cats, "2024-01", set())
        assert result == []


# ---------------------------------------------------------------------------
# compute_category_averages
# ---------------------------------------------------------------------------

class TestComputeCategoryAverages:
    def test_basic_average(self):
        cats = [make_cat("cat1", "Groceries")]
        txns = [
            make_tx("t1", "2024-01-01", -200_000),
            make_tx("t2", "2024-02-01", -400_000),
        ]
        result = compute_category_averages(txns, cats)
        assert len(result) == 1
        assert result[0]["average_amount"] == 300_000

    def test_inflows_excluded_from_average(self):
        cats = [make_cat("cat1", "Salary")]
        txns = [
            make_tx("t1", "2024-01-01", 5_000_000),  # income — skipped
        ]
        result = compute_category_averages(txns, cats)
        assert result == []

    def test_outlier_month_excluded_from_average(self):
        # 5 normal months at ~$100, one spike at $10,000 — spike should be excluded
        cats = [make_cat("cat1", "Car")]
        txns = [
            make_tx("t1", "2024-01-01", -100_000),
            make_tx("t2", "2024-02-01", -105_000),
            make_tx("t3", "2024-03-01", -95_000),
            make_tx("t4", "2024-04-01", -110_000),
            make_tx("t5", "2024-05-01", -98_000),
            make_tx("t6", "2024-06-01", -10_000_000),  # outlier spike
        ]
        result = compute_category_averages(txns, cats)
        row = result[0]
        assert row["outlier_months_excluded"] == 1
        # IQR-adjusted average should be close to $100 (not inflated by spike)
        assert row["average_amount"] < 200_000
        # Raw average includes the spike — much higher
        assert row["raw_average_amount"] > row["average_amount"]

    def test_fewer_than_5_months_no_outlier_exclusion(self):
        cats = [make_cat("cat1", "Groceries")]
        txns = [
            make_tx("t1", "2024-01-01", -100_000),
            make_tx("t2", "2024-02-01", -100_000),
            make_tx("t3", "2024-03-01", -100_000),
            make_tx("t4", "2024-04-01", -100_000),
        ]
        result = compute_category_averages(txns, cats)
        assert result[0]["outlier_months_excluded"] == 0

    def test_sorted_descending_by_average(self):
        cats = [
            make_cat("cat1", "Dining"),
            make_cat("cat2", "Groceries"),
        ]
        txns = [
            make_tx("t1", "2024-01-01", -100_000, "cat1"),
            make_tx("t2", "2024-01-01", -500_000, "cat2"),
        ]
        result = compute_category_averages(txns, cats)
        assert result[0]["category_id"] == "cat2"

    def test_unknown_category_skipped(self):
        cats = [make_cat("cat1", "Groceries")]
        txns = [
            make_tx("t1", "2024-01-01", -200_000, category_id="no-such-cat"),
        ]
        result = compute_category_averages(txns, cats)
        assert result == []

    def test_empty_transactions_returns_empty(self):
        cats = [make_cat("cat1", "Groceries")]
        result = compute_category_averages([], cats)
        assert result == []
