import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.ai.knowledge_seed import SEED_VERSION, seed_knowledge_base


class _FakeCollection:
    def __init__(self):
        self.entries = {
            "seed_0": {"source": "seed", "topic": "价格"},
            "manual_0": {"source": "manual", "topic": "群规"},
        }
        self.deleted = []
        self.added = None

    def get(self, include):
        ids = list(self.entries)
        return {"ids": ids, "metadatas": [self.entries[item] for item in ids]}

    def delete(self, ids):
        self.deleted.extend(ids)
        for doc_id in ids:
            self.entries.pop(doc_id, None)

    def count(self):
        return len(self.entries)

    def add(self, **kwargs):
        self.added = kwargs


class _FakeVectorStore:
    def __init__(self):
        self.knowledge_base = _FakeCollection()


class _FakeEmbeddingManager:
    def embed(self, texts):
        return [[float(index)] for index, _ in enumerate(texts)]


def test_seed_migration_removes_only_legacy_seed_documents():
    vector_store = _FakeVectorStore()

    result = asyncio.run(seed_knowledge_base(vector_store, _FakeEmbeddingManager()))

    assert result == 0
    assert vector_store.knowledge_base.deleted == ["seed_0"]
    assert vector_store.knowledge_base.added is None


def test_fresh_seed_documents_are_versioned():
    vector_store = _FakeVectorStore()
    vector_store.knowledge_base.entries = {}

    result = asyncio.run(seed_knowledge_base(vector_store, _FakeEmbeddingManager()))

    assert result > 0
    assert all(
        metadata["seed_version"] == SEED_VERSION
        for metadata in vector_store.knowledge_base.added["metadatas"]
    )
