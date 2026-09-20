"""Unit tests for user preferences contracts (dashboard widget layout)."""

import pytest
from pydantic import ValidationError

from src.models.contracts.user_preferences import MAX_DASHBOARD_WIDGETS, PreferencesData


@pytest.mark.unit
class TestDashboardWidgetsContract:
    """Validator coverage for the typed widgets layout on PreferencesData."""

    def test_widgets_none_by_default(self):
        """Legacy payloads without widgets default to None."""
        prefs = PreferencesData.model_validate({})
        assert prefs.widgets is None
        assert prefs.columns.visible == []

    def test_widgets_explicit_none(self):
        """Explicit null widgets validate to None (validator None path)."""
        prefs = PreferencesData.model_validate({"widgets": None})
        assert prefs.widgets is None

    def test_widgets_valid_list(self):
        """Ordered items with id and visible validate; order preserved."""
        prefs = PreferencesData.model_validate(
            {
                "widgets": [
                    {"id": "quick-stats", "visible": True},
                    {"id": "recent-activity", "visible": False},
                ]
            }
        )
        assert prefs.widgets is not None
        assert [w.id for w in prefs.widgets] == ["quick-stats", "recent-activity"]
        assert [w.visible for w in prefs.widgets] == [True, False]

    def test_widgets_visible_defaults_true(self):
        """Visible defaults to True when omitted."""
        prefs = PreferencesData.model_validate({"widgets": [{"id": "quick-stats"}]})
        assert prefs.widgets is not None
        assert prefs.widgets[0].visible is True

    def test_widgets_duplicate_ids_rejected(self):
        """Duplicate widget ids raise a validation error."""
        with pytest.raises(ValidationError):
            PreferencesData.model_validate(
                {
                    "widgets": [
                        {"id": "quick-stats", "visible": True},
                        {"id": "quick-stats", "visible": False},
                    ]
                }
            )

    def test_widgets_invalid_id_rejected(self):
        """Widget ids outside the bounded pattern raise a validation error."""
        with pytest.raises(ValidationError):
            PreferencesData.model_validate({"widgets": [{"id": "not a valid id!"}]})

    def test_widgets_oversize_rejected(self):
        """More than MAX_DASHBOARD_WIDGETS items raise a validation error."""
        oversize = [{"id": f"widget-{i}"} for i in range(MAX_DASHBOARD_WIDGETS + 1)]
        with pytest.raises(ValidationError):
            PreferencesData.model_validate({"widgets": oversize})
