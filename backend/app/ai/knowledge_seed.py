"""知识库种子数据初始化。

将基础业务知识（FAQ、流程、群规等）写入向量数据库，
使 AI 在回答时可以检索到这些信息。
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

SEED_VERSION = 2

SEED_DOCUMENTS: list[dict] = [
    {
        "text": "业务价格、服务范围、接单状态、订单状态、预计完成时间、工作时间和退款规则不在默认知识库中固定，必须以当前后端 business_context 或人工确认结果为准。",
        "topic": "价格",
        "priority": "high",
    },
    {
        "text": "未配置的游戏服务、价格、订单流程、账号安全承诺和售后承诺不得向用户承诺；只有后端当前配置明确提供的内容才能作为回复依据。",
        "topic": "流程",
        "priority": "high",
    },
    {
        "text": "用户咨询游戏服务时，应先参考后端 business_context 的 enabled、services、status_text、is_working_now、next_available_at 和 notes 字段，不得用知识库中的历史或默认内容覆盖实时业务数据。",
        "topic": "流程",
        "priority": "medium",
    },
    {
        "text": "除非后端业务上下文明确配置并适用于当前问题，不得承诺服务人员筛选、服务保障、账号安全、退款或订单完成时间。",
        "topic": "服务",
        "priority": "medium",
    },
    {
        "text": "退款和售后规则不使用默认政策推断；无法从当前后端业务数据确认时，应直接说明需要人工确认。",
        "topic": "售后",
        "priority": "high",
    },
    {
        "text": "群规：禁止发布广告、色情、暴力等违规内容。禁止私下交易，所有订单需通过正规流程。禁止辱骂、骚扰他人。违规者将被移出群聊。",
        "topic": "群规",
        "priority": "high",
    },
    {
        "text": "工作时间和当前接单状态不能根据本地时间推算；仅使用后端提供的 is_working_now、status_text 和 next_available_at。",
        "topic": "服务",
        "priority": "low",
    },
    {
        "text": "支持的游戏和服务列表不采用默认清单；只有 business_context.services 中明确列出的项目才视为已配置。",
        "topic": "服务",
        "priority": "medium",
    },
]


def _remove_legacy_seed_documents(collection) -> int:
    """Remove old default business facts without touching manual documents."""

    try:
        result = collection.get(include=["metadatas"])
        ids = result.get("ids") or []
        metadatas = result.get("metadatas") or []
        legacy_ids = [
            doc_id
            for doc_id, metadata in zip(ids, metadatas)
            if isinstance(metadata, dict)
            and metadata.get("source") == "seed"
            and metadata.get("seed_version") != SEED_VERSION
        ]
        if not legacy_ids:
            return 0

        collection.delete(ids=legacy_ids)
        logger.info("已移除 %d 条旧版知识库种子数据", len(legacy_ids))
        return len(legacy_ids)
    except Exception as exc:
        logger.warning("清理旧版知识库种子数据失败: %s", exc)
        return 0


async def seed_knowledge_base(vector_store, embedding_manager) -> int:
    """将种子知识写入向量数据库。

    仅当知识库为空时才写入，避免重复。

    Args:
        vector_store: VectorStoreManager 实例。
        embedding_manager: EmbeddingManager 实例。

    Returns:
        写入的文档数量。
    """
    _remove_legacy_seed_documents(vector_store.knowledge_base)

    try:
        existing = vector_store.knowledge_base.count()
        if existing > 0:
            logger.info(f"知识库已有 {existing} 条记录，跳过种子初始化")
            return 0
    except Exception:
        pass

    texts = [d["text"] for d in SEED_DOCUMENTS]
    metadatas = [
        {
            "source": "seed",
            "seed_version": SEED_VERSION,
            "topic": d["topic"],
            "priority": d["priority"],
            "added_at": time.time(),
        }
        for d in SEED_DOCUMENTS
    ]
    ids = [f"seed_{i}" for i in range(len(texts))]

    embeddings = embedding_manager.embed(texts)
    vector_store.knowledge_base.add(
        ids=ids,
        documents=texts,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    logger.info(f"知识库种子数据已初始化: {len(texts)} 条文档")
    return len(texts)
