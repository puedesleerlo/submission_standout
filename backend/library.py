"""Reusable, source-backed banks. Revisions and project snapshots are append-only."""
from datetime import date
from typing import Literal

from pydantic import Field

from backend.schemas import StrictModel
from backend.service import ConflictError
from backend.store import digest

Bank = Literal["Fact", "Experience", "Company", "Person", "Hiring signal", "Research", "Artifact", "Idea"]
BANKS = ["Fact", "Experience", "Company", "Person", "Hiring signal", "Research", "Artifact", "Idea"]


class Source(StrictModel):
    reference: str = Field(min_length=3, max_length=2000)
    locator: str = Field(default="", max_length=500)
    accessed_on: date
    note: str = Field(default="", max_length=1000)


class BankEntry(StrictModel):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,119}$")
    bank: Bank
    title: str = Field(min_length=2, max_length=140)
    body: str = Field(min_length=15, max_length=20000)
    status: Literal["User supplied", "Documented", "Hypothesis"] = "User supplied"
    sources: list[Source] = Field(min_length=1, max_length=12)
    tags: list[str] = Field(default_factory=list, max_length=20)
    company: str = Field(default="", max_length=160)
    event_date: date | None = None
    caveats: str = Field(default="", max_length=3000)


class BankBatch(StrictModel):
    entries: list[BankEntry] = Field(min_length=1, max_length=100)


class BankSelection(StrictModel):
    entry_ids: list[str] = Field(min_length=1, max_length=100)


class Library:
    def __init__(self, store):
        self.store = store

    def latest(self, conn):
        entries = {}
        for row in self.store.list(conn, "bank_entry"):
            entries[row["key"]] = row
        return list(entries.values())

    def search(self, conn, bank=None, query="", company="", offset=0, limit=50):
        rows = [row for row in self.latest(conn)
                if (not bank or row["bank"] == bank)
                and (not company or company.casefold() == row["company"].casefold())
                and (not query or query.casefold() in " ".join([
                    row["title"], row["body"], row["key"], *row["tags"]]).casefold())]
        return {"total": len(rows), "offset": offset, "entries": rows[offset:offset + limit]}

    def save(self, conn, payload):
        previous = next((r for r in self.latest(conn) if r["key"] == payload["key"]), None)
        content_hash = digest(payload)
        if previous and previous["content_hash"] == content_hash:
            return previous
        value = {**payload, "content_hash": content_hash,
                 "revision": previous["revision"] + 1 if previous else 1,
                 "previous_id": previous["id"] if previous else None}
        row = self.store.add(conn, "bank_entry", "library", value)
        self.store.event(conn, "library", "bank.saved", {"entry_id": row["id"], "key": row["key"]})
        return row

    def attach(self, conn, project_id, entry_ids):
        project = self.store.get(conn, "project", project_id)
        # Resolve the entire selection before writing; invalid batches cannot partially import.
        entries = [self.store.get(conn, "bank_entry", eid) for eid in dict.fromkeys(entry_ids)]
        attached = self.store.list(conn, "evidence", project_id)
        results = []
        for entry in entries:
            existing = next((e for e in attached if e.get("bank_entry_id") == entry["id"]), None)
            if existing:
                results.append(existing)
                continue
            if any(e.get("bank_key") == entry["key"] for e in attached):
                raise ConflictError("This project already has a different revision of that bank entry. Keep its frozen evidence or use a new project.")
            kind = {"Fact": "Experience", "Company": "Institution", "Person": "Institution",
                    "Hiring signal": "Institution"}.get(entry["bank"], entry["bank"])
            body = entry["body"] + ("\n\nCaveats: " + entry["caveats"] if entry["caveats"] else "")
            item = self.store.add(conn, "evidence", project_id, {
                "title": entry["title"], "body": body, "kind": kind, "status": entry["status"],
                "source": " | ".join(s["reference"] + (" — " + s["locator"] if s["locator"] else "") for s in entry["sources"]),
                "sources": entry["sources"], "synthetic": project["synthetic"],
                "bank_entry_id": entry["id"], "bank_key": entry["key"], "bank_revision": entry["revision"],
            })
            self.store.event(conn, project_id, "evidence.imported", {"evidence_id": item["id"], "bank_entry_id": entry["id"]})
            attached.append(item)
            results.append(item)
        return {"evidence": results}
