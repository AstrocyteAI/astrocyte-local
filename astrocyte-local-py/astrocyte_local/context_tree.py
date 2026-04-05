"""Context Tree — hierarchical markdown file storage.

Stores memories as .md files with YAML frontmatter in a domain-based
directory structure. See docs/context-tree-format.md for the spec.

All operations are sync (file I/O). Async wrappers in engine.py.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


@dataclass
class MemoryEntry:
    """A single memory stored as a markdown file."""

    id: str
    bank_id: str
    text: str
    domain: str
    file_path: str  # Relative to memory root
    memory_layer: str = "fact"  # "fact", "observation", "model"
    fact_type: str = "world"  # "world", "experience", "observation"
    tags: list[str] = field(default_factory=list)
    created_at: str = ""  # ISO 8601
    updated_at: str = ""
    occurred_at: str | None = None
    recall_count: int = 0
    last_recalled_at: str | None = None
    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ContextTree:
    """Hierarchical markdown file storage for memories.

    Directory structure:
        {root}/memory/{domain}/{filename}.md

    Each .md file has YAML frontmatter + plain text content.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.memory_dir = self.root / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def store(
        self,
        content: str,
        bank_id: str,
        *,
        domain: str = "general",
        tags: list[str] | None = None,
        memory_layer: str = "fact",
        fact_type: str = "world",
        occurred_at: str | None = None,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        """Store a new memory as a markdown file. Returns the created entry."""
        mem_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        filename = self._make_filename(content)

        # Ensure domain directory exists
        domain_dir = self.memory_dir / domain
        domain_dir.mkdir(parents=True, exist_ok=True)

        # Handle filename collisions
        file_path = domain_dir / f"{filename}.md"
        counter = 2
        while file_path.exists():
            file_path = domain_dir / f"{filename}-{counter}.md"
            counter += 1

        rel_path = str(file_path.relative_to(self.memory_dir))

        entry = MemoryEntry(
            id=mem_id,
            bank_id=bank_id,
            text=content,
            domain=domain,
            file_path=rel_path,
            memory_layer=memory_layer,
            fact_type=fact_type,
            tags=tags or [],
            created_at=now,
            updated_at=now,
            occurred_at=occurred_at,
            source=source,
            metadata=metadata or {},
        )

        self._write_entry(file_path, entry)
        return entry

    def read(self, entry_id: str) -> MemoryEntry | None:
        """Read a memory by ID. Scans all files. Returns None if not found."""
        for entry in self.scan_all():
            if entry.id == entry_id:
                return entry
        return None

    def update(self, entry_id: str, content: str) -> MemoryEntry | None:
        """Update a memory's content. Returns updated entry or None."""
        for md_file in self.memory_dir.rglob("*.md"):
            entry = self._read_file(md_file)
            if entry and entry.id == entry_id:
                entry.text = content
                entry.updated_at = datetime.now(timezone.utc).isoformat()
                self._write_entry(md_file, entry)
                return entry
        return None

    def delete(self, entry_id: str) -> bool:
        """Delete a memory by ID. Returns True if found and deleted."""
        for md_file in self.memory_dir.rglob("*.md"):
            entry = self._read_file(md_file)
            if entry and entry.id == entry_id:
                md_file.unlink()
                # Remove empty domain directories
                parent = md_file.parent
                if parent != self.memory_dir and not any(parent.iterdir()):
                    parent.rmdir()
                return True
        return False

    def record_recall(self, entry_id: str) -> None:
        """Increment recall_count and update last_recalled_at for an entry."""
        for md_file in self.memory_dir.rglob("*.md"):
            entry = self._read_file(md_file)
            if entry and entry.id == entry_id:
                entry.recall_count += 1
                entry.last_recalled_at = datetime.now(timezone.utc).isoformat()
                self._write_entry(md_file, entry)
                return

    def list_domains(self, bank_id: str | None = None) -> list[str]:
        """List all domain directories."""
        domains: list[str] = []
        if not self.memory_dir.exists():
            return domains
        for d in sorted(self.memory_dir.iterdir()):
            if d.is_dir() and not d.name.startswith("_"):
                if bank_id is None:
                    domains.append(d.name)
                else:
                    # Check if any file in this domain matches the bank
                    for md in d.glob("*.md"):
                        entry = self._read_file(md)
                        if entry and entry.bank_id == bank_id:
                            domains.append(d.name)
                            break
        return domains

    def list_entries(self, bank_id: str, domain: str | None = None) -> list[MemoryEntry]:
        """List entries in a domain (or all domains) for a bank."""
        entries: list[MemoryEntry] = []
        search_dir = self.memory_dir / domain if domain else self.memory_dir
        if not search_dir.exists():
            return entries
        for md_file in sorted(search_dir.rglob("*.md")):
            entry = self._read_file(md_file)
            if entry and entry.bank_id == bank_id:
                entries.append(entry)
        return entries

    def scan_all(self, bank_id: str | None = None) -> list[MemoryEntry]:
        """Scan all memory files. Optionally filter by bank_id."""
        entries: list[MemoryEntry] = []
        if not self.memory_dir.exists():
            return entries
        for md_file in sorted(self.memory_dir.rglob("*.md")):
            entry = self._read_file(md_file)
            if entry:
                if bank_id is None or entry.bank_id == bank_id:
                    entries.append(entry)
        return entries

    def count(self, bank_id: str | None = None) -> int:
        """Count total memories."""
        return len(self.scan_all(bank_id))

    # ── Internal ──

    def _make_filename(self, content: str) -> str:
        """Generate a filename from content (first 50 chars, slugified)."""
        slug = content[:50].lower().strip()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        slug = slug.strip("-")
        return slug or "memory"

    def _write_entry(self, path: Path, entry: MemoryEntry) -> None:
        """Write a MemoryEntry as a markdown file with YAML frontmatter."""
        frontmatter: dict[str, Any] = {
            "id": entry.id,
            "bank_id": entry.bank_id,
            "memory_layer": entry.memory_layer,
            "fact_type": entry.fact_type,
            "tags": entry.tags,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
            "recall_count": entry.recall_count,
        }
        if entry.occurred_at:
            frontmatter["occurred_at"] = entry.occurred_at
        if entry.last_recalled_at:
            frontmatter["last_recalled_at"] = entry.last_recalled_at
        if entry.source:
            frontmatter["source"] = entry.source
        if entry.metadata:
            frontmatter["metadata"] = entry.metadata

        fm_str = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
        path.write_text(f"---\n{fm_str}---\n\n{entry.text}\n", encoding="utf-8")

    def _read_file(self, path: Path) -> MemoryEntry | None:
        """Read a markdown file and parse into MemoryEntry."""
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        # Parse YAML frontmatter
        if not content.startswith("---"):
            return None

        parts = content.split("---", 2)
        if len(parts) < 3:
            return None

        try:
            fm = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            return None

        text = parts[2].strip()
        rel_path = str(path.relative_to(self.memory_dir))
        domain = path.parent.name if path.parent != self.memory_dir else "general"

        return MemoryEntry(
            id=fm.get("id", ""),
            bank_id=fm.get("bank_id", ""),
            text=text,
            domain=domain,
            file_path=rel_path,
            memory_layer=fm.get("memory_layer", "fact"),
            fact_type=fm.get("fact_type", "world"),
            tags=fm.get("tags", []),
            created_at=fm.get("created_at", ""),
            updated_at=fm.get("updated_at", ""),
            occurred_at=fm.get("occurred_at"),
            recall_count=fm.get("recall_count", 0),
            last_recalled_at=fm.get("last_recalled_at"),
            source=fm.get("source"),
            metadata=fm.get("metadata", {}),
        )
