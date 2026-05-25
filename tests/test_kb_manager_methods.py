"""Unit tests for KBManager and KBEvolution methods lacking direct coverage.

Covers:
  - KBManager.correct() — correction by key, audit logging, KeyError
  - KBEvolution._apply_decay() — zero rate, archived, manual override
  - KBEvolution._generalize_patterns() — grouping, edge cases
  - KBEvolution._archive_low_confidence() — threshold, failure count
  - KBManager.evolve() — full cycle delegation
  - KBManager.seed_from_static_analysis() — Python/Java seeding
"""

import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from uibridge.kb.item import KBItem, Confidence, KnowledgeSource
from uibridge.kb.store import KBStore
from uibridge.kb.manager import KBManager
from uibridge.kb.evolution import KBEvolution


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════

def _make_item(category, key, item_id, score=0.5, source=KnowledgeSource.STATIC_ANALYSIS,
               value=None, description="", tags=None, archived=False,
               self_test_failures=0, decay_rate=None, manual_override=None,
               last_validated_at=None, version=1):
    """Create a KBItem with sensible defaults for testing."""
    conf = Confidence(
        score=score,
        source=source,
        self_test_failures=self_test_failures,
        decay_rate=decay_rate,
        manual_override=manual_override,
        last_validated_at=last_validated_at if last_validated_at is not None else time.time(),
    )
    return KBItem(
        id=item_id,
        category=category,
        key=key,
        value=value or {},
        confidence=conf,
        description=description,
        tags=tags or [],
        version=version,
        archived=archived,
    )


# ══════════════════════════════════════════════════════════════
# TestKBManagerCorrect
# ══════════════════════════════════════════════════════════════

class TestKBManagerCorrect:
    """KBManager.correct() — human correction via NL feedback."""

    def test_correct_existing_item(self):
        """Correcting an existing item updates value, increments version, adds tag."""
        with tempfile.TemporaryDirectory() as td:
            mgr = KBManager(td)
            item = _make_item(
                "components", "component_type.table", "table_001",
                score=0.7,
                value={"class_name": "WebTable", "xpath": "//table[@id='users']"},
                description="Table component",
            )
            mgr.store.save(item)

            corrected = mgr.correct(
                "components", "table_001",
                {"xpath": "//table[@data-testid='users']"},
                nl_note="Changed locator to data-testid",
            )

            assert corrected.value["xpath"] == "//table[@data-testid='users']"
            assert corrected.value["class_name"] == "WebTable"  # untouched
            assert corrected.version == 2  # incremented
            assert "corrected" in corrected.tags
            assert corrected.description == "Changed locator to data-testid"

    def test_correct_nonexistent_item_raises_keyerror(self):
        """Correcting a non-existent item raises KeyError."""
        with tempfile.TemporaryDirectory() as td:
            mgr = KBManager(td)
            with pytest.raises(KeyError, match="KB item not found"):
                mgr.correct("components", "nonexistent_001", {"xpath": "//btn"})

    def test_correct_with_audit_logger(self):
        """When audit_logger is provided, correct() logs the change."""
        with tempfile.TemporaryDirectory() as td:
            mock_audit = MagicMock()
            mgr = KBManager(td, audit_logger=mock_audit)
            item = _make_item(
                "components", "component_type.button", "btn_001",
                score=0.6,
                value={"class_name": "WebButton"},
                description="Button component",
            )
            mgr.store.save(item)

            mgr.correct(
                "components", "btn_001",
                {"class_name": "CustomButton"},
                nl_note="Renamed button",
            )

            assert mock_audit.log.called
            # log(action, target, before, after, source=..., note=...) — action/target are positional
            call_args = mock_audit.log.call_args
            assert call_args[0][0] == "kb.modify"         # action (positional)
            assert call_args[0][1] == "components/btn_001" # target (positional)
            assert call_args[1]["note"] == "Renamed button"

    def test_correct_confidence_override(self):
        """Confidence override in corrections sets manual_override."""
        with tempfile.TemporaryDirectory() as td:
            mgr = KBManager(td)
            item = _make_item(
                "conventions", "convention.locator_priority", "loc_001",
                score=0.5,
                value={"priority": ["id", "xpath"]},
            )
            mgr.store.save(item)

            corrected = mgr.correct(
                "conventions", "loc_001",
                {"priority": ["data-testid", "id"], "confidence_override": 0.95},
            )

            assert corrected.confidence.manual_override == 0.95
            assert corrected.confidence.effective_score == 0.95

    def test_correct_preserves_existing_value_keys_not_in_corrections(self):
        """Only the keys in corrections are updated; existing keys stay."""
        with tempfile.TemporaryDirectory() as td:
            mgr = KBManager(td)
            item = _make_item(
                "patterns", "pattern.search_flow", "pat_001",
                score=0.55,
                value={"steps": ["enter", "click"], "frequency": 5},
            )
            mgr.store.save(item)

            corrected = mgr.correct(
                "patterns", "pat_001",
                {"steps": ["enter", "click", "assert"]},
            )

            assert corrected.value["steps"] == ["enter", "click", "assert"]
            assert corrected.value["frequency"] == 5

    def test_correct_empty_nl_note_keeps_original_description(self):
        """When nl_note is empty, original description is preserved."""
        with tempfile.TemporaryDirectory() as td:
            mgr = KBManager(td)
            item = _make_item(
                "components", "component_type.input", "input_001",
                value={"class_name": "WebInput"},
                description="Original input description",
            )
            mgr.store.save(item)

            corrected = mgr.correct(
                "components", "input_001",
                {"class_name": "EnhancedInput"},
                nl_note="",
            )

            assert corrected.description == "Original input description"


# ══════════════════════════════════════════════════════════════
# TestKBApplyDecay
# ══════════════════════════════════════════════════════════════

class TestKBApplyDecay:
    """KBEvolution._apply_decay() — time-based confidence decay."""

    def test_decay_applied_to_item_with_old_last_validated(self):
        """Item with old last_validated_at has effective score reduced."""
        with tempfile.TemporaryDirectory() as td:
            store = KBStore(td)
            item = _make_item(
                "components", "component.test_decay", "decay_001",
                score=0.8,
                source=KnowledgeSource.LLM_INFERENCE,  # decay_rate=0.008
                last_validated_at=time.time() - 864000,  # ~10 days ago
            )
            store.save(item)
            original = item.confidence.score

            evolution = KBEvolution(store)
            evolution._apply_decay()

            updated = store.get("components", "decay_001")
            assert updated is not None
            # effective_score at creation already accounted for days, but
            # _apply_decay sets score = effective_score (which was already
            # lower due to time passage). So after saving again, score < original.
            assert updated.confidence.score < original, \
                f"Expected {updated.confidence.score} < {original}"

    def test_decay_zero_rate_skips_item(self):
        """Item with decay_rate=0 should not change."""
        with tempfile.TemporaryDirectory() as td:
            store = KBStore(td)
            item = _make_item(
                "components", "component.stable", "stable_001",
                score=0.9,
                source=KnowledgeSource.HUMAN_INJECTION,  # decay_rate=0
                last_validated_at=time.time() - 864000,
            )
            store.save(item)
            original = item.confidence.score

            evolution = KBEvolution(store)
            evolution._apply_decay()

            updated = store.get("components", "stable_001")
            assert updated.confidence.score == original

    def test_decay_skips_archived(self):
        """Archived items should not be decayed."""
        with tempfile.TemporaryDirectory() as td:
            store = KBStore(td)
            item = _make_item(
                "components", "component.archived", "arch_001",
                score=0.5,
                source=KnowledgeSource.LLM_INFERENCE,
                last_validated_at=time.time() - 864000,
                archived=True,
            )
            store.save(item)
            original = item.confidence.score

            evolution = KBEvolution(store)
            evolution._apply_decay()

            updated = store.get("components", "arch_001")
            assert updated.confidence.score == original

    def test_decay_manual_override_does_not_prevent_decay_on_base_score(self):
        """Manual override sets effective_score but _apply_decay operates on base score.

        The _apply_decay method compares effective_score to score.
        With a manual_override, effective_score can be higher than score,
        so decay only applies when effective_score < score.
        This test verifies that with manual_override == score, no decay writes happen.
        """
        with tempfile.TemporaryDirectory() as td:
            store = KBStore(td)
            item = _make_item(
                "components", "component.override", "ovr_001",
                score=0.5,
                source=KnowledgeSource.LLM_INFERENCE,
                last_validated_at=time.time() - 864000,
                manual_override=0.9,  # override is high, effective_score=0.9 > base 0.5
            )
            store.save(item)
            original_score = item.confidence.score

            evolution = KBEvolution(store)
            evolution._apply_decay()

            # effective_score (0.9, from override) > score (0.5), so no save trigger
            updated = store.get("components", "ovr_001")
            assert updated.confidence.score == original_score

    def test_decay_recently_validated_not_affected(self):
        """Item validated just now has no accumulated decay."""
        with tempfile.TemporaryDirectory() as td:
            store = KBStore(td)
            now = time.time()
            item = _make_item(
                "components", "component.fresh", "fresh_001",
                score=0.7,
                source=KnowledgeSource.PATTERN_MINING,  # decay_rate=0.01
                last_validated_at=now,  # just now
            )
            store.save(item)

            # effective_score: base = 0.7, days = 0, score stays 0.7
            assert item.confidence.effective_score == pytest.approx(0.7, abs=0.01)

            evolution = KBEvolution(store)
            evolution._apply_decay()

            updated = store.get("components", "fresh_001")
            # effective_score (0.7) == score (0.7), so no save triggered
            assert updated.confidence.score == pytest.approx(0.7, abs=0.01)

    def test_decay_on_empty_store(self):
        """Decay on empty store should not crash."""
        with tempfile.TemporaryDirectory() as td:
            store = KBStore(td)
            evolution = KBEvolution(store)
            evolution._apply_decay()  # no exception


# ══════════════════════════════════════════════════════════════
# TestKBGeneralizePatterns
# ══════════════════════════════════════════════════════════════

class TestKBGeneralizePatterns:
    """KBEvolution._generalize_patterns() — pattern extraction from similar items."""

    def test_empty_store_no_op(self):
        """Generalization on empty store should not crash."""
        with tempfile.TemporaryDirectory() as td:
            store = KBStore(td)
            evolution = KBEvolution(store)
            evolution._generalize_patterns()  # no exception

    def test_single_item_no_generalization(self):
        """A single item cannot form a group of 3, so no generalization."""
        with tempfile.TemporaryDirectory() as td:
            store = KBStore(td)
            item = _make_item(
                "components", "component.only_one", "one_001",
                score=0.5,
                value={"xpath": "//table", "role": "table"},
            )
            store.save(item)

            evolution = KBEvolution(store)
            evolution._generalize_patterns()

            updated = store.get("components", "one_001")
            assert updated is not None
            assert "generalized" not in updated.tags
            assert updated.confidence.score == pytest.approx(0.5, abs=0.001)

    def test_two_items_no_generalization(self):
        """Two items with same signature don't generalize (<3 threshold)."""
        with tempfile.TemporaryDirectory() as td:
            store = KBStore(td)
            for i in range(2):
                item = _make_item(
                    "components", f"component.two_{i}", f"two_{i:03d}",
                    score=0.5,
                    value={"xpath": "//table", "role": "table"},
                )
                store.save(item)

            evolution = KBEvolution(store)
            evolution._generalize_patterns()

            for i in range(2):
                updated = store.get("components", f"two_{i:03d}")
                assert "generalized" not in updated.tags

    def test_three_items_same_signature_get_generalized(self):
        """Three items with the same value structure get boosted and tagged."""
        with tempfile.TemporaryDirectory() as td:
            store = KBStore(td)
            for i in range(3):
                item = _make_item(
                    "components", f"component.gen_{i}", f"gen_{i:03d}",
                    score=0.6,
                    value={"xpath": "//table", "role": "table"},
                )
                store.save(item)

            evolution = KBEvolution(store)
            evolution._generalize_patterns()

            for i in range(3):
                updated = store.get("components", f"gen_{i:03d}")
                assert updated is not None
                assert "generalized" in updated.tags
                assert updated.confidence.score > 0.64, \
                    f"Score should be boosted above 0.64, got {updated.confidence.score}"

    def test_different_signature_no_grouping(self):
        """Items with different value structures don't form a group."""
        with tempfile.TemporaryDirectory() as td:
            store = KBStore(td)
            for i, val in enumerate([
                {"xpath": "//table", "role": "table"},
                {"xpath": "//button", "role": "button"},
                {"class_name": "WebInput", "events": ["change"]},
            ]):
                item = _make_item(
                    "components", f"component.diff_{i}", f"diff_{i:03d}",
                    score=0.6,
                    value=val,
                )
                store.save(item)

            evolution = KBEvolution(store)
            evolution._generalize_patterns()

            for i in range(3):
                updated = store.get("components", f"diff_{i:03d}")
                assert "generalized" not in updated.tags

    def test_only_one_category_reaches_threshold(self):
        """Mix of signatures: only one category has 3+ items.

        _value_signature groups by keys+types, not values. So two groups with
        the same keys but different values merge. We must use distinct key-sets
        so button items don't blend into the table group.
        """
        with tempfile.TemporaryDirectory() as td:
            store = KBStore(td)
            # 3 table items (same keys+types) → will generalize
            for i in range(3):
                store.save(_make_item(
                    "components", f"component.tbl_{i}", f"tbl_{i:03d}",
                    score=0.6,
                    value={"xpath": "//table", "role": "table"},
                ))
            # 2 button items (different key-set) → won't merge with tables, won't generalize
            for i in range(2):
                store.save(_make_item(
                    "components", f"component.btn_{i}", f"btn_{i:03d}",
                    score=0.6,
                    value={"xpath": "//button", "event": "click"},
                ))

            evolution = KBEvolution(store)
            evolution._generalize_patterns()

            # table items generalized
            for i in range(3):
                updated = store.get("components", f"tbl_{i:03d}")
                assert "generalized" in updated.tags
            # button items NOT generalized
            for i in range(2):
                updated = store.get("components", f"btn_{i:03d}")
                assert "generalized" not in updated.tags

    def test_pages_category_also_checked(self):
        """_generalize_patterns also checks pages and patterns categories."""
        with tempfile.TemporaryDirectory() as td:
            store = KBStore(td)
            for i in range(3):
                store.save(_make_item(
                    "pages", f"pages.page_{i}", f"pg_{i:03d}",
                    score=0.55,
                    value={"url": "/users", "method": "GET"},
                ))

            evolution = KBEvolution(store)
            evolution._generalize_patterns()

            for i in range(3):
                updated = store.get("pages", f"pg_{i:03d}")
                assert "generalized" in updated.tags

    def test_patterns_category_checked(self):
        """_generalize_patterns checks the patterns category."""
        with tempfile.TemporaryDirectory() as td:
            store = KBStore(td)
            for i in range(3):
                store.save(_make_item(
                    "patterns", f"patterns.flow_{i}", f"flow_{i:03d}",
                    score=0.5,
                    value={"steps": ["click", "assert"]},
                ))

            evolution = KBEvolution(store)
            evolution._generalize_patterns()

            for i in range(3):
                updated = store.get("patterns", f"flow_{i:03d}")
                assert "generalized" in updated.tags


# ══════════════════════════════════════════════════════════════
# TestKBArchiveLowConfidence
# ══════════════════════════════════════════════════════════════

class TestKBArchiveLowConfidence:
    """KBEvolution._archive_low_confidence() — archives items below threshold."""

    def test_item_below_threshold_with_failures_archived(self):
        """Item with effective_score<0.2 and 3+ failures gets archived."""
        with tempfile.TemporaryDirectory() as td:
            store = KBStore(td)
            item = _make_item(
                "components", "component.bad_one", "bad_001",
                score=0.1,
                source=KnowledgeSource.LLM_INFERENCE,
                self_test_failures=5,
            )
            store.save(item)

            evolution = KBEvolution(store)
            evolution._archive_low_confidence()

            # After archive(), item is moved to archive dir, get() returns None
            updated = store.get("components", "bad_001")
            assert updated is None, "Item should have been moved to archive"

    def test_low_confidence_no_failures_preserved(self):
        """Item below 0.2 but with <3 failures is not archived."""
        with tempfile.TemporaryDirectory() as td:
            store = KBStore(td)
            item = _make_item(
                "components", "component.weak", "weak_001",
                score=0.15,
                self_test_failures=2,  # below 3
            )
            store.save(item)

            evolution = KBEvolution(store)
            evolution._archive_low_confidence()

            updated = store.get("components", "weak_001")
            assert updated is not None, "Item with <3 failures should be preserved"
            assert updated.archived is False

    def test_high_confidence_item_preserved(self):
        """Item with high confidence should not be archived."""
        with tempfile.TemporaryDirectory() as td:
            store = KBStore(td)
            item = _make_item(
                "components", "component.strong", "strong_001",
                score=0.9,
                self_test_failures=10,  # many failures but high confidence
            )
            store.save(item)

            evolution = KBEvolution(store)
            evolution._archive_low_confidence()

            updated = store.get("components", "strong_001")
            assert updated is not None
            assert updated.archived is False

    def test_exactly_at_threshold_preserved(self):
        """Item with effective_score exactly at threshold (0.2) is preserved.

        Uses decay_rate=0 so time passage does not nudge effective_score below
        the threshold before the archive check runs.
        """
        with tempfile.TemporaryDirectory() as td:
            store = KBStore(td)
            item = _make_item(
                "conventions", "conv.borderline", "border_001",
                score=0.2,
                decay_rate=0.0,  # prevent time-based drift
                self_test_failures=4,
            )
            store.save(item)

            evolution = KBEvolution(store)
            evolution._archive_low_confidence(threshold=0.2)

            updated = store.get("conventions", "border_001")
            assert updated is not None, \
                "Item at threshold should be preserved (effective_score < threshold, not <=)"
            # Note: condition is effective_score < threshold, so 0.2 < 0.2 is False
            assert updated.archived is False

    def test_custom_threshold_used(self):
        """Higher custom threshold archives more items."""
        with tempfile.TemporaryDirectory() as td:
            store = KBStore(td)
            item = _make_item(
                "components", "component.mid", "mid_001",
                score=0.3,
                self_test_failures=3,
            )
            store.save(item)

            evolution = KBEvolution(store)
            evolution._archive_low_confidence(threshold=0.5)

            updated = store.get("components", "mid_001")
            assert updated is None, \
                "Item below custom threshold of 0.5 should be archived"

    def test_archived_items_skipped(self):
        """Already archived items are not processed again."""
        with tempfile.TemporaryDirectory() as td:
            store = KBStore(td)
            item = _make_item(
                "components", "component.already_arch", "arch_already_001",
                score=0.1,
                self_test_failures=5,
                archived=True,
            )
            # Save to archive dir since it's already archived
            store.save(item)  # This puts it in the regular dir
            # Simulate archive
            store.archive(item)

            evolution = KBEvolution(store)
            evolution._archive_low_confidence()

            # The archive file should exist.
            archive_file = store.root / "archive" / "arch_already_001.yaml"
            assert archive_file.exists(), "Archived item should remain in archive"


# ══════════════════════════════════════════════════════════════
# TestKBManagerEvolve
# ══════════════════════════════════════════════════════════════

class TestKBManagerEvolve:
    """KBManager.evolve() delegates to KBEvolution.evolve()."""

    def test_evolve_runs_full_cycle(self):
        """evolve() runs decay, generalization, and archiving in sequence."""
        with tempfile.TemporaryDirectory() as td:
            mgr = KBManager(td)

            # Add some items: one old+stale (will decay and archive),
            # three similar (will generalize)
            old_stale = _make_item(
                "components", "component.stale", "stale_001",
                score=0.15,
                source=KnowledgeSource.LLM_INFERENCE,
                self_test_failures=3,
                last_validated_at=time.time() - 864000,
            )
            mgr.store.save(old_stale)

            for i in range(3):
                mgr.store.save(_make_item(
                    "components", f"component.sim_{i}", f"sim_{i:03d}",
                    score=0.6,
                    value={"xpath": "//table", "role": "table"},
                ))

            # Run evolve
            mgr.evolve()

            # Stale item should be archived
            stale = mgr.store.get("components", "stale_001")
            assert stale is None, "Stale item should have been archived"

            # Similar items should be generalized
            for i in range(3):
                sim = mgr.store.get("components", f"sim_{i:03d}")
                assert sim is not None
                assert "generalized" in sim.tags

    def test_evolve_empty_store_no_crash(self):
        """Evolve on empty store should not crash."""
        with tempfile.TemporaryDirectory() as td:
            mgr = KBManager(td)
            mgr.evolve()  # no exception


# ══════════════════════════════════════════════════════════════
# TestKBSeedFromStaticAnalysis
# ══════════════════════════════════════════════════════════════

class TestKBSeedFromStaticAnalysis:
    """KBManager.seed_from_static_analysis() — bulk seeding from source dirs."""

    def test_seed_from_python_component_aw(self):
        """Seeds from Python ComponentAW files in component_aw category."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            aw_dir = root / "aw"
            aw_dir.mkdir()
            (aw_dir / "table_aw.py").write_text("""class TableAW:
    \"\"\"Table component wrapper.\"\"\"
    def get_row_count(self):
        return self.driver.find_elements_by_xpath("//tr")
    def click_cell(self, row, col):
        pass
""", encoding="utf-8")

            mgr = KBManager(str(root))
            items = mgr.seed_from_static_analysis({"component_aw": "aw"})
            assert len(items) > 0
            assert any("TableAW" in str(item.value) or "table" in item.key
                       for item in items)

    def test_seed_from_python_page_files(self):
        """Seeds from Python page files."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pages_dir = root / "pages"
            pages_dir.mkdir()
            (pages_dir / "login_page.py").write_text("""class LoginPage:
    \"\"\"Login page object.\"\"\"
    def enter_username(self, username):
        pass
    def click_login(self):
        pass
""", encoding="utf-8")

            mgr = KBManager(str(root))
            items = mgr.seed_from_static_analysis({"pages": "pages"})
            # May produce items; at minimum, shouldn't crash
            assert isinstance(items, list)

    def test_seed_from_python_test_scripts(self):
        """Seeds from Python test scripts."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            test_dir = root / "tests"
            test_dir.mkdir()
            (test_dir / "test_login.py").write_text("""import pytest
def test_valid_login():
    page = LoginPage()
    page.login("user", "pass")
    assert page.is_logged_in()
""", encoding="utf-8")

            mgr = KBManager(str(root))
            items = mgr.seed_from_static_analysis({"tests": "tests"})
            assert isinstance(items, list)

    def test_seed_from_java_files(self):
        """Seeds from Java files in page/test categories."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pages_dir = root / "src" / "pages"
            pages_dir.mkdir(parents=True)
            (pages_dir / "HomePage.java").write_text("""package pages;
import components.*;
public class HomePage extends BasePage {
    private WebTable userTable;
    public void search(String keyword) {}
}
""", encoding="utf-8")

            mgr = KBManager(str(root))
            items = mgr.seed_from_static_analysis({"pages": "src/pages"})
            assert isinstance(items, list)

    def test_seed_from_java_test_files(self):
        """Seeds from Java test files."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            test_dir = root / "src" / "test"
            test_dir.mkdir(parents=True)
            (test_dir / "TestLogin.java").write_text("""package tests;
import org.testng.annotations.Test;
public class TestLogin {
    @Test
    public void testValidLogin() {
        LoginPage page = new LoginPage();
        page.login("admin", "pass");
    }
}
""", encoding="utf-8")

            mgr = KBManager(str(root))
            items = mgr.seed_from_static_analysis({"tests": "src/test"})
            assert isinstance(items, list)

    def test_seed_from_nonexistent_dir(self):
        """Seeding from a nonexistent directory is a no-op, not a crash."""
        with tempfile.TemporaryDirectory() as td:
            mgr = KBManager(td)
            items = mgr.seed_from_static_analysis({"component_aw": "nonexistent"})
            assert items == []

    def test_seed_unknown_category_skipped(self):
        """Unknown category names are silently skipped."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            some_dir = root / "some_dir"
            some_dir.mkdir()
            (some_dir / "file.py").write_text("x = 1\n", encoding="utf-8")

            mgr = KBManager(str(root))
            items = mgr.seed_from_static_analysis({"unknown_cat": "some_dir"})
            assert items == []

    def test_seed_empty_source_dirs(self):
        """Empty source_dirs returns empty list."""
        with tempfile.TemporaryDirectory() as td:
            mgr = KBManager(td)
            items = mgr.seed_from_static_analysis({})
            assert items == []

    def test_seed_saves_items_to_store(self):
        """Seeded items are persisted in the KBStore."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            aw_dir = root / "aw"
            aw_dir.mkdir()
            (aw_dir / "button_aw.py").write_text("""class ButtonAW:
    def click(self):
        pass
""", encoding="utf-8")

            mgr = KBManager(str(root))
            items = mgr.seed_from_static_analysis({"component_aw": "aw"})
            assert len(items) > 0

            # Verify items are persisted
            all_items = mgr.store.list_all()
            assert len(all_items) >= len(items)

    def test_seed_both_python_and_java(self):
        """Seeds from both Python and Java sources in the same run."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Python file in component_aw
            aw_dir = root / "aw"
            aw_dir.mkdir()
            (aw_dir / "table_aw.py").write_text("""class TableAW:
    def get_rows(self):
        return []
""", encoding="utf-8")

            # Java test files
            test_dir = root / "java_tests"
            test_dir.mkdir(parents=True)
            (test_dir / "TestSearch.java").write_text("""package tests;
import org.testng.annotations.Test;
public class TestSearch {
    @Test
    public void testSearch() {}
}
""", encoding="utf-8")

            mgr = KBManager(str(root))
            items = mgr.seed_from_static_analysis({
                "component_aw": "aw",
                "tests": "java_tests",
            })
            assert len(items) > 0


# ══════════════════════════════════════════════════════════════
# TestKBValueSignature
# ══════════════════════════════════════════════════════════════

class TestKBValueSignature:
    """KBEvolution._value_signature() static method."""

    def test_empty_dict(self):
        sig = KBEvolution._value_signature({})
        assert sig == ""

    def test_same_keys_produce_same_signature(self):
        sig1 = KBEvolution._value_signature({"a": 1, "b": "hello"})
        sig2 = KBEvolution._value_signature({"a": 99, "b": "world"})
        assert sig1 == sig2

    def test_different_keys_produce_different_signature(self):
        sig1 = KBEvolution._value_signature({"a": 1, "b": 2})
        sig2 = KBEvolution._value_signature({"a": 1, "c": 2})
        assert sig1 != sig2

    def test_different_types_produce_different_signature(self):
        sig1 = KBEvolution._value_signature({"a": 1})       # int
        sig2 = KBEvolution._value_signature({"a": "1"})     # str
        assert sig1 != sig2
