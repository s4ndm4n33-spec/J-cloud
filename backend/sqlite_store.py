"""Small async Mongo-shaped persistence adapter backed by shard-local SQLite."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any


class Cursor:
    def __init__(self, docs: list[dict[str, Any]]):
        self.docs = docs

    def sort(self, key_or_list: Any, direction: int | None = None) -> "Cursor":
        if isinstance(key_or_list, list):
            key, direction = key_or_list[0]
        else:
            key = key_or_list
        reverse = direction == -1
        self.docs.sort(key=lambda doc: doc.get(key) or "", reverse=reverse)
        return self

    def limit(self, count: int) -> "Cursor":
        self.docs = self.docs[:count]
        return self

    def __aiter__(self) -> "Cursor":
        self._iter_index = 0
        return self

    async def __anext__(self) -> dict[str, Any]:
        if self._iter_index >= len(self.docs):
            raise StopAsyncIteration
        doc = self.docs[self._iter_index]
        self._iter_index += 1
        return doc

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        return self.docs[:length]


class SQLiteCollection:
    def __init__(self, conn: sqlite3.Connection, name: str):
        self.conn = conn
        self.name = name

    async def create_index(self, *_args: Any, **_kwargs: Any) -> str:
        return "sqlite-json-index"

    async def insert_one(self, doc: dict[str, Any]) -> Any:
        stored = dict(doc)
        stored.setdefault("_id", uuid.uuid4().hex)
        await asyncio.to_thread(self._insert_sync, stored)
        return type("InsertOneResult", (), {"inserted_id": stored["_id"]})()

    def _insert_sync(self, doc: dict[str, Any]) -> None:
        self.conn.execute(
            "insert into documents(collection, doc_id, body) values (?, ?, ?)",
            (self.name, str(doc["_id"]), json.dumps(doc, default=str)),
        )
        self.conn.commit()

    async def find_one(self, filt: dict[str, Any], projection: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any] | None:
        docs = await asyncio.to_thread(self._all_sync)
        if kwargs.get("sort"):
            docs = Cursor(docs).sort(kwargs["sort"]).docs
        for doc in docs:
            if _matches(doc, filt):
                return _project(doc, projection)
        return None

    def find(self, filt: dict[str, Any] | None = None, projection: dict[str, Any] | None = None) -> Cursor:
        docs = self._all_sync()
        return Cursor([_project(doc, projection) for doc in docs if _matches(doc, filt or {})])

    async def update_one(self, filt: dict[str, Any], update: dict[str, Any], upsert: bool = False) -> Any:
        docs = await asyncio.to_thread(self._all_sync)
        for doc in docs:
            if _matches(doc, filt):
                _apply_update(doc, update)
                await asyncio.to_thread(self._replace_sync, doc)
                return type("UpdateResult", (), {"matched_count": 1, "modified_count": 1})()
        if upsert:
            doc = dict(filt)
            _apply_update(doc, update)
            await self.insert_one(doc)
        return type("UpdateResult", (), {"matched_count": 0, "modified_count": 0})()

    async def delete_one(self, filt: dict[str, Any]) -> Any:
        docs = await asyncio.to_thread(self._all_sync)
        for doc in docs:
            if _matches(doc, filt):
                await asyncio.to_thread(self._delete_sync, str(doc["_id"]))
                return type("DeleteResult", (), {"deleted_count": 1})()
        return type("DeleteResult", (), {"deleted_count": 0})()

    async def count_documents(self, filt: dict[str, Any]) -> int:
        docs = await asyncio.to_thread(self._all_sync)
        return sum(1 for doc in docs if _matches(doc, filt))

    async def delete_many(self, filt: dict[str, Any]) -> Any:
        docs = await asyncio.to_thread(self._all_sync)
        deleted = 0
        for doc in docs:
            if _matches(doc, filt):
                await asyncio.to_thread(self._delete_sync, str(doc["_id"]))
                deleted += 1
        return type("DeleteResult", (), {"deleted_count": deleted})()

    def _all_sync(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "select body from documents where collection = ?", (self.name,)
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def _replace_sync(self, doc: dict[str, Any]) -> None:
        self.conn.execute(
            "update documents set body = ? where collection = ? and doc_id = ?",
            (json.dumps(doc, default=str), self.name, str(doc["_id"])),
        )
        self.conn.commit()

    def _delete_sync(self, doc_id: str) -> None:
        self.conn.execute(
            "delete from documents where collection = ? and doc_id = ?", (self.name, doc_id)
        )
        self.conn.commit()


class SQLiteDatabase:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute(
            "create table if not exists documents(collection text not null, doc_id text not null, body text not null, primary key(collection, doc_id))"
        )
        self.conn.commit()

    def __getattr__(self, name: str) -> SQLiteCollection:
        return SQLiteCollection(self.conn, name)

    def __getitem__(self, name: str) -> SQLiteCollection:
        return SQLiteCollection(self.conn, name)


class SQLiteClient:
    def __init__(self, path: Path):
        self.db = SQLiteDatabase(path)

    def __getitem__(self, _name: str) -> SQLiteDatabase:
        return self.db

    def close(self) -> None:
        self.db.conn.close()


def _matches(doc: dict[str, Any], filt: dict[str, Any]) -> bool:
    for key, expected in filt.items():
        actual = doc.get(key)
        if isinstance(expected, dict):
            if "$gt" in expected and not (actual is not None and str(actual) > str(expected["$gt"])):
                return False
            if "$gte" in expected and not (actual is not None and str(actual) >= str(expected["$gte"])):
                return False
            if "$lte" in expected and not (actual is not None and str(actual) <= str(expected["$lte"])):
                return False
            if "$in" in expected and actual not in expected["$in"]:
                return False
        elif actual != expected:
            return False
    return True


def _project(doc: dict[str, Any], projection: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(doc)
    if projection and projection.get("_id") == 0:
        out.pop("_id", None)
    return out


def _apply_update(doc: dict[str, Any], update: dict[str, Any]) -> None:
    if "$set" in update:
        doc.update(update["$set"])
    if "$inc" in update:
        for key, value in update["$inc"].items():
            parts = key.split(".")
            target = doc
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = target.get(parts[-1], 0) + value
