"""Tests for Context Tree — markdown file CRUD."""

from pathlib import Path

from astrocyte_local.context_tree import ContextTree


class TestContextTreeStore:
    def test_store_creates_file(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        entry = tree.store("Calvin prefers dark mode", bank_id="project", domain="preferences")

        assert entry.id
        assert entry.bank_id == "project"
        assert entry.domain == "preferences"
        assert entry.text == "Calvin prefers dark mode"
        assert (tmp_path / "memory" / "preferences" / f"{entry.file_path.split('/')[-1]}").exists()

    def test_store_default_domain(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        entry = tree.store("test", bank_id="project")
        assert entry.domain == "general"

    def test_store_with_tags(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        entry = tree.store("tagged", bank_id="project", tags=["ui", "preference"])
        assert entry.tags == ["ui", "preference"]

    def test_store_handles_collision(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        e1 = tree.store("same content", bank_id="project", domain="test")
        e2 = tree.store("same content", bank_id="project", domain="test")
        assert e1.file_path != e2.file_path
        assert e1.id != e2.id

    def test_store_creates_domain_directory(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        tree.store("test", bank_id="project", domain="new-domain")
        assert (tmp_path / "memory" / "new-domain").is_dir()


class TestContextTreeRead:
    def test_read_existing(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        stored = tree.store("findable content", bank_id="project")
        found = tree.read(stored.id)
        assert found is not None
        assert found.text == "findable content"
        assert found.id == stored.id

    def test_read_nonexistent(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        assert tree.read("nonexistent") is None


class TestContextTreeUpdate:
    def test_update_content(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        stored = tree.store("original", bank_id="project")
        updated = tree.update(stored.id, "modified")
        assert updated is not None
        assert updated.text == "modified"

        # Verify on disk
        read_back = tree.read(stored.id)
        assert read_back.text == "modified"

    def test_update_nonexistent(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        assert tree.update("nonexistent", "new") is None


class TestContextTreeDelete:
    def test_delete_existing(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        stored = tree.store("to delete", bank_id="project", domain="temp")
        assert tree.delete(stored.id) is True
        assert tree.read(stored.id) is None

    def test_delete_nonexistent(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        assert tree.delete("nonexistent") is False

    def test_delete_removes_empty_domain(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        stored = tree.store("only entry", bank_id="project", domain="lonely")
        tree.delete(stored.id)
        assert not (tmp_path / "memory" / "lonely").exists()


class TestContextTreeScan:
    def test_scan_all(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        tree.store("one", bank_id="project")
        tree.store("two", bank_id="project")
        tree.store("three", bank_id="other")

        all_entries = tree.scan_all()
        assert len(all_entries) == 3

    def test_scan_by_bank(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        tree.store("project entry", bank_id="project")
        tree.store("other entry", bank_id="other")

        project_only = tree.scan_all(bank_id="project")
        assert len(project_only) == 1
        assert project_only[0].text == "project entry"

    def test_list_domains(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        tree.store("a", bank_id="project", domain="alpha")
        tree.store("b", bank_id="project", domain="beta")

        domains = tree.list_domains("project")
        assert "alpha" in domains
        assert "beta" in domains

    def test_list_entries_in_domain(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        tree.store("pref 1", bank_id="project", domain="preferences")
        tree.store("pref 2", bank_id="project", domain="preferences")
        tree.store("arch 1", bank_id="project", domain="architecture")

        prefs = tree.list_entries("project", domain="preferences")
        assert len(prefs) == 2

    def test_count(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        assert tree.count() == 0
        tree.store("one", bank_id="project")
        tree.store("two", bank_id="project")
        assert tree.count() == 2
        assert tree.count(bank_id="project") == 2
        assert tree.count(bank_id="other") == 0


class TestContextTreeRecall:
    def test_record_recall(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        stored = tree.store("recallable", bank_id="project")
        assert stored.recall_count == 0

        tree.record_recall(stored.id)
        read_back = tree.read(stored.id)
        assert read_back.recall_count == 1
        assert read_back.last_recalled_at is not None

    def test_record_recall_increments(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        stored = tree.store("multi recall", bank_id="project")
        tree.record_recall(stored.id)
        tree.record_recall(stored.id)
        tree.record_recall(stored.id)

        read_back = tree.read(stored.id)
        assert read_back.recall_count == 3


class TestContextTreeFileFormat:
    def test_file_is_valid_markdown(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        entry = tree.store("Hello world", bank_id="project", domain="test", tags=["greeting"])

        file_path = tmp_path / "memory" / entry.file_path
        content = file_path.read_text()

        assert content.startswith("---\n")
        assert "Hello world" in content
        assert "greeting" in content

    def test_file_roundtrip(self, tmp_path: Path):
        tree = ContextTree(tmp_path)
        stored = tree.store(
            "Complex content with\nmultiple lines",
            bank_id="bank-1",
            domain="test",
            tags=["tag1", "tag2"],
            memory_layer="observation",
            source="api:test",
        )

        read_back = tree.read(stored.id)
        assert read_back.text == "Complex content with\nmultiple lines"
        assert read_back.tags == ["tag1", "tag2"]
        assert read_back.memory_layer == "observation"
        assert read_back.source == "api:test"
        assert read_back.bank_id == "bank-1"
