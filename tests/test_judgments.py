from stratum.db.judgment_lifecycle import JudgmentLifecyclePolicy


def test_judgment_lifecycle_uses_expected_verification_date_for_due_check():
    policy = JudgmentLifecyclePolicy()

    early = policy.evaluate_due(
        {"result": "pending", "expected_verification": "review on 2026-06-10"},
        end_period="2026-05-31",
    )
    due = policy.evaluate_due(
        {"result": "pending", "expected_verification": "review on 2026-06-10"},
        end_period="2026-06-10",
    )

    assert early.is_due is False
    assert early.basis == "expected_verification"
    assert due.is_due is True
    assert due.due_date == "2026-06-10"


def test_judgment_lifecycle_falls_back_to_created_at_when_expected_date_is_free_text():
    policy = JudgmentLifecyclePolicy()

    decision = policy.evaluate_due(
        {
            "result": None,
            "expected_verification": "check next week",
            "created_at": "2026-05-30T08:00:00+08:00",
        },
        end_period="2026-05-31",
    )

    assert decision.is_due is True
    assert decision.basis == "created_at"


def test_judgment_lifecycle_excludes_completed_judgments_from_due_check():
    policy = JudgmentLifecyclePolicy()

    decision = policy.evaluate_due(
        {
            "result": "supported",
            "expected_verification": "2026-05-30",
            "created_at": "2026-05-01T00:00:00",
        },
        end_period="2026-05-31",
    )

    assert decision.is_due is False
    assert decision.basis == "result"


def test_judgment_lifecycle_normalizes_richer_review_states():
    policy = JudgmentLifecyclePolicy()

    assert policy.review_state({"result": "confirmed"}).state == "supported"
    invalidated = policy.review_state({"result": "expired"})
    deferred = policy.review_state({"result": "deferred"})

    assert invalidated.state == "invalidated"
    assert invalidated.confidence_effect < policy.review_state({"result": "challenged"}).confidence_effect
    assert invalidated.is_terminal is True
    assert deferred.state == "deferred"
    assert deferred.is_pending is True


def test_judgment_lifecycle_due_check_includes_deferred_reviews():
    policy = JudgmentLifecyclePolicy()

    decision = policy.evaluate_due(
        {
            "result": "deferred",
            "expected_verification": "2026-05-30",
            "created_at": "2026-05-01T00:00:00",
        },
        end_period="2026-05-31",
    )

    assert decision.is_due is True
    assert decision.basis == "expected_verification"


def test_judgment_lifecycle_preserves_existing_review_fields():
    class Row(dict):
        def __getitem__(self, key):
            return dict.__getitem__(self, key)

    policy = JudgmentLifecyclePolicy()

    preserved = policy.preserve_judgment_verification(Row({
        "result": "correct",
        "verified_at": "2026-06-01",
        "verified_by_scale": "weekly",
        "actual_outcome": "confirmed",
    }))

    assert preserved == {
        "result": "correct",
        "verified_at": "2026-06-01",
        "verified_by_scale": "weekly",
        "actual_outcome": "confirmed",
    }
