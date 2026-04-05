"""Search engine — SQLite FTS5 full-text search.

See docs/search-contract.md for the behavior specification.
All operations are sync. Async wrappers in engine.py.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from astrocyte_local.context_tree import ContextTree, MemoryEntry


@dataclass
class SearchHit:
    """A single search result."""

    id: str
    text: str
    score: float  # 0.0 – 1.0 normalized
    bank_id: str
    domain: str
    file_path: str
    memory_layer: str | None = None
    fact_type: str | None = None
    tags: list[str] | None = None
    occurred_at: str | None = None
    metadata: dict[str, Any] | None = None


class SearchEngine:
    """SQLite FTS5 full-text search over the Context Tree.

    Index is stored in {root}/_search.db. Rebuilt on startup if stale.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        """Create FTS5 virtual table if it doesn't exist."""
        self._conn.executescript("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                id,
                bank_id,
                text,
                tags,
                domain,
                memory_layer,
                fact_type,
                file_path,
                tokenize='porter unicode61'
            );
        """)
        self._conn.commit()

    def build_index(self, tree: ContextTree, bank_id: str | None = None) -> int:
        """Rebuild the FTS index from the Context Tree. Returns count indexed."""
        # Clear existing entries for the bank
        if bank_id:
            self._conn.execute("DELETE FROM memory_fts WHERE bank_id = ?", (bank_id,))
        else:
            self._conn.execute("DELETE FROM memory_fts")

        entries = tree.scan_all(bank_id)
        for entry in entries:
            self._add_entry(entry)

        self._conn.commit()
        return len(entries)

    def search(
        self,
        query: str,
        bank_id: str,
        *,
        limit: int = 10,
        tags: list[str] | None = None,
        layers: list[str] | None = None,
    ) -> list[SearchHit]:
        """Full-text search. Returns scored hits sorted by relevance."""
        if query.strip() == "*":
            return self._search_all(bank_id, limit=limit, tags=tags, layers=layers)

        # FTS5 query — escape special characters
        fts_query = self._escape_fts_query(query)
        if not fts_query:
            return []

        try:
            rows = self._conn.execute(
                """
                SELECT id, bank_id, text, tags, domain, memory_layer, fact_type, file_path,
                       rank
                FROM memory_fts
                WHERE memory_fts MATCH ? AND bank_id = ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, bank_id, limit * 3),  # Over-fetch for post-filtering
            ).fetchall()
        except sqlite3.OperationalError:
            return []

        hits = self._rows_to_hits(rows)

        # Post-filter by tags
        if tags:
            tag_set = set(tags)
            hits = [h for h in hits if h.tags and tag_set.issubset(set(h.tags))]

        # Post-filter by layers
        if layers:
            hits = [h for h in hits if h.memory_layer in layers]

        return hits[:limit]

    def add_document(self, entry: MemoryEntry) -> None:
        """Add a single entry to the index (incremental update)."""
        self._add_entry(entry)
        self._conn.commit()

    def remove_document(self, entry_id: str) -> None:
        """Remove a single entry from the index."""
        self._conn.execute("DELETE FROM memory_fts WHERE id = ?", (entry_id,))
        self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    # ── Internal ──

    def _add_entry(self, entry: MemoryEntry) -> None:
        """Insert an entry into FTS index."""
        self._conn.execute(
            """
            INSERT INTO memory_fts (id, bank_id, text, tags, domain, memory_layer, fact_type, file_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.id,
                entry.bank_id,
                entry.text,
                " ".join(entry.tags),
                entry.domain,
                entry.memory_layer,
                entry.fact_type,
                entry.file_path,
            ),
        )

    def _search_all(
        self,
        bank_id: str,
        *,
        limit: int = 1000,
        tags: list[str] | None = None,
        layers: list[str] | None = None,
    ) -> list[SearchHit]:
        """Return all entries for a bank (wildcard query)."""
        rows = self._conn.execute(
            "SELECT id, bank_id, text, tags, domain, memory_layer, fact_type, file_path, 0 as rank "
            "FROM memory_fts WHERE bank_id = ? LIMIT ?",
            (bank_id, limit),
        ).fetchall()

        hits = self._rows_to_hits(rows, default_score=1.0)

        if tags:
            tag_set = set(tags)
            hits = [h for h in hits if h.tags and tag_set.issubset(set(h.tags))]
        if layers:
            hits = [h for h in hits if h.memory_layer in layers]

        return hits

    def _rows_to_hits(self, rows: list[sqlite3.Row], default_score: float | None = None) -> list[SearchHit]:
        """Convert database rows to SearchHit objects with normalized scores."""
        if not rows:
            return []

        hits: list[SearchHit] = []
        # Normalize BM25 scores (more negative = more relevant)
        raw_scores = [abs(float(row["rank"])) for row in rows]
        max_score = max(raw_scores) if raw_scores and max(raw_scores) > 0 else 1.0

        for row in rows:
            if default_score is not None:
                score = default_score
            else:
                score = abs(float(row["rank"])) / max_score if max_score > 0 else 0.5

            tag_str = row["tags"] or ""
            tags = [t for t in tag_str.split() if t]

            hits.append(
                SearchHit(
                    id=row["id"],
                    text=row["text"],
                    score=score,
                    bank_id=row["bank_id"],
                    domain=row["domain"],
                    file_path=row["file_path"],
                    memory_layer=row["memory_layer"],
                    fact_type=row["fact_type"],
                    tags=tags,
                )
            )

        return hits

    @staticmethod
    def _escape_fts_query(query: str) -> str:
        """Escape special FTS5 characters for safe querying.

        Does NOT quote individual tokens — quoting disables stemming.
        Instead, strips FTS5 special characters and lets the tokenizer handle it.
        """
        # Remove characters that have special meaning in FTS5
        cleaned = query.replace('"', " ").replace("'", " ")
        cleaned = cleaned.replace("(", " ").replace(")", " ")
        cleaned = cleaned.replace(":", " ").replace("^", " ")
        # Split and rejoin to normalize whitespace
        tokens = cleaned.split()
        if not tokens:
            return ""
        return " ".join(tokens)
