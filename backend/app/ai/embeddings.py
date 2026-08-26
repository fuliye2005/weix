"""Embedding 管理器。

将文本转换为向量，用于语义检索和去重检测。

支持的 Embedding 后端（按优先级）：
1. local — 本地 sentence-transformers 模型（默认，离线可用，零 API 依赖）
2. siliconflow — SiliconFlow API (BAAI/bge-large-zh-v1.5)
3. openai — OpenAI text-embedding-3-small
4. dashscope — 阿里云 DashScope text-embedding-v3

注意：DeepSeek 不支持 embeddings API，不要使用。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

LOCAL_EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
LOCAL_EMBEDDING_DIMENSION = 384

PROVIDER_EMBEDDING_MODELS: dict[str, str] = {
    "siliconflow": "BAAI/bge-large-zh-v1.5",
    "openai": "text-embedding-3-small",
    "dashscope": "text-embedding-v3",
    "local": LOCAL_EMBEDDING_MODEL,
}

PROVIDER_EMBEDDING_URLS: dict[str, str] = {
    "siliconflow": "https://api.siliconflow.cn/v1",
    "openai": "https://api.openai.com/v1",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
}

PROVIDER_DIMENSIONS: dict[str, int] = {
    "local": 384,
    "siliconflow": 1024,
    "openai": 1536,
    "dashscope": 1024,
}

PROVIDER_API_KEY_ENV: dict[str, str] = {
    "siliconflow": "SILICONFLOW_API_KEY",
    "openai": "OPENAI_API_KEY",
    "dashscope": "DASHSCOPE_API_KEY",
}

DEFAULT_EMBEDDING_CONFIG: dict[str, str] = {
    "provider": "local",
    "model": LOCAL_EMBEDDING_MODEL,
    "base_url": "",
}

DEFAULT_BATCH_SIZE = 20


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def is_usable_api_key(value: Any) -> bool:
    """判断密钥是否像真实配置，而不是模板中的占位文本。"""
    secret = _clean_text(value).lower()
    if not secret:
        return False
    return not secret.startswith((
        "sk-your-",
        "your-",
        "change-me",
        "replace-me",
        "<your-",
    ))


def get_embedding_settings() -> dict[str, str]:
    """读取当前 Embedding 配置，并解析 provider 对应的 API Key。

    没有 ``ai.embedding`` 的旧配置继续使用本地模型；云端 Embedding
    只使用对应供应商的 Key，避免把聊天服务的密钥误发到另一家接口。
    """
    settings = dict(DEFAULT_EMBEDDING_CONFIG)
    ai_cfg: Mapping[str, Any] = {}

    try:
        from app.config import get_config

        configured = get_config().ai
        if isinstance(configured, Mapping):
            ai_cfg = configured
    except Exception as exc:  # pragma: no cover - only during early bootstrap
        logger.debug("读取 Embedding 配置失败，使用默认值: %s", exc)

    raw = ai_cfg.get("embedding")
    raw_provider = ""
    raw_model = ""
    raw_base_url = ""
    api_key = ""
    if isinstance(raw, Mapping):
        raw_provider = _clean_text(raw.get("provider")).lower()
        raw_model = _clean_text(raw.get("model"))
        raw_base_url = _clean_text(raw.get("base_url"))
        api_key = _clean_text(raw.get("api_key"))

    provider = raw_provider or _clean_text(settings.get("provider")).lower()
    if provider not in {"local", "siliconflow", "openai", "dashscope"}:
        provider = "local"

    settings["provider"] = provider
    settings["model"] = raw_model or PROVIDER_EMBEDDING_MODELS.get(
        provider, LOCAL_EMBEDDING_MODEL
    )
    settings["base_url"] = raw_base_url or PROVIDER_EMBEDDING_URLS.get(provider, "")

    env_name = PROVIDER_API_KEY_ENV.get(provider, "")
    env_key = os.getenv(env_name, "") if env_name else ""
    resolved_key = api_key if is_usable_api_key(api_key) else ""
    if not resolved_key and is_usable_api_key(env_key):
        resolved_key = _clean_text(env_key)
    if not resolved_key and provider != "local":
        # 同一供应商可以复用聊天 Key；不同供应商不交叉复用。
        if _clean_text(ai_cfg.get("provider")).lower() == provider:
            chat_key = ai_cfg.get("api_key")
            if is_usable_api_key(chat_key):
                resolved_key = _clean_text(chat_key)

    settings["api_key"] = resolved_key
    return settings


def _sentence_transformers_cache_dirs() -> list[Path]:
    """返回 sentence-transformers/HuggingFace 常见本地缓存目录。"""
    candidates: list[Path] = []
    for env_name in ("SENTENCE_TRANSFORMERS_HOME", "HF_HOME"):
        value = os.getenv(env_name)
        if value:
            candidates.append(Path(value))

    home = Path.home()
    candidates.extend([
        home / ".cache" / "torch" / "sentence_transformers",
        home / ".cache" / "huggingface" / "hub",
    ])
    return candidates


def can_load_local_embedding(model: str = LOCAL_EMBEDDING_MODEL) -> bool:
    """判断本地 embedding 模型是否可离线加载。"""
    model_dir_name = f"sentence-transformers_{model.replace('/', '_')}"
    hub_dir_name = f"models--sentence-transformers--{model.replace('/', '--')}"
    for cache_dir in _sentence_transformers_cache_dirs():
        if (cache_dir / model_dir_name).exists() or (cache_dir / hub_dir_name).exists():
            return True
    return False


def get_local_embedding_cache_status(model: str = LOCAL_EMBEDDING_MODEL) -> str:
    """返回本地 embedding 模型缓存状态文案。"""
    if can_load_local_embedding(model):
        return "已缓存"
    return "未缓存，将在后台自动下载"


class EmbeddingManager:
    """Embedding 管理器。

    默认使用本地 sentence-transformers 模型（离线、零 API 成本）。
    可通过 provider 参数切换到 API 后端。

    Attributes:
        _provider: 当前后端名称。
        _client: embedding 客户端（SentenceTransformer 或 OpenAIEmbeddings）。
        _dimension: embedding 向量维度。
    """

    def __init__(
        self,
        provider: str = "local",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self._provider = provider
        self._model = model or PROVIDER_EMBEDDING_MODELS.get(provider, LOCAL_EMBEDDING_MODEL)
        self._dimension = PROVIDER_DIMENSIONS.get(provider, LOCAL_EMBEDDING_DIMENSION)
        self._client = None
        self._api_key = api_key
        self._base_url = base_url

        logger.info(
            f"EmbeddingManager configured: provider={provider}, model={self._model}, dim={self._dimension}"
        )

    # ------------------------------------------------------------------
    # 延迟初始化
    # ------------------------------------------------------------------

    def _ensure_client(self):
        """延迟初始化 embedding 客户端（首次调用时才加载模型/创建连接）。"""
        if self._client is not None:
            return

        if self._provider == "local":
            self._init_local()
        else:
            self._init_api()

    def _init_local(self) -> None:
        """初始化本地 sentence-transformers 模型。"""
        try:
            from sentence_transformers import SentenceTransformer

            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

            allow_download = not can_load_local_embedding(self._model)
            if allow_download:
                logger.info(
                    "本地 Embedding 模型未找到，开始后台下载: %s。"
                    "首次下载可能需要几分钟，请保持网络连接。",
                    self._model,
                )
            else:
                logger.info("正在加载本地 Embedding 模型: %s", self._model)

            self._client = SentenceTransformer(
                self._model,
                local_files_only=not allow_download,
            )
            self._dimension = self._client.get_embedding_dimension()
            logger.info(
                "本地 Embedding 模型已就绪: %s, dim=%s",
                self._model,
                self._dimension,
            )
        except Exception as exc:
            logger.error(
                "本地 Embedding 模型加载/下载失败: %s。请检查网络，"
                "或预先下载 sentence-transformers/%s。",
                exc,
                self._model,
            )
            raise

    def _init_api(self) -> None:
        """初始化 API 后端。"""
        try:
            from langchain_openai import OpenAIEmbeddings

            configured = get_embedding_settings()
            configured_provider = configured.get("provider", "local")
            api_key = self._api_key
            base_url = self._base_url
            if self._provider == configured_provider:
                api_key = api_key or configured.get("api_key", "")
                base_url = base_url or configured.get("base_url", "")
            else:
                env_name = PROVIDER_API_KEY_ENV.get(self._provider, "")
                api_key = api_key or (os.getenv(env_name, "") if env_name else "")
                base_url = base_url or PROVIDER_EMBEDDING_URLS.get(self._provider, "")

            if not is_usable_api_key(api_key):
                env_name = PROVIDER_API_KEY_ENV.get(self._provider, "")
                hint = f"环境变量 {env_name}" if env_name else "ai.embedding.api_key"
                raise ValueError(
                    f"{self._provider} Embedding API Key 未配置，请填写 {hint}"
                )

            kwargs: dict = {
                "model": self._model,
                "openai_api_key": api_key,
                "openai_api_base": base_url,
            }

            self._client = OpenAIEmbeddings(**kwargs)
            logger.info(
                f"API embedding client initialized: provider={self._provider}, model={self._model}"
            )
        except Exception as exc:
            logger.error(f"Failed to initialize API embedding client: {exc}")
            raise

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def dimension(self) -> int:
        self._ensure_client()
        return self._dimension

    # ------------------------------------------------------------------
    # Embedding API
    # ------------------------------------------------------------------

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量文本转向量。"""
        if not texts:
            return []

        self._ensure_client()

        embeddings = []
        for i in range(0, len(texts), DEFAULT_BATCH_SIZE):
            batch = texts[i : i + DEFAULT_BATCH_SIZE]

            if self._provider == "local":
                batch_embeddings = self._client.encode(
                    batch, normalize_embeddings=True
                ).tolist()
            else:
                batch_embeddings = self._client.embed_documents(batch)

            embeddings.extend(batch_embeddings)
            if batch_embeddings:
                self._dimension = len(batch_embeddings[0])

        logger.debug(f"Embedded {len(texts)} texts, dim={self._dimension}")
        return embeddings

    def embed_query(self, text: str) -> list[float]:
        """单条查询文本转向量。"""
        if not text:
            self._ensure_client()
            return [0.0] * self._dimension

        self._ensure_client()

        if self._provider == "local":
            vec = self._client.encode(text, normalize_embeddings=True).tolist()
            if isinstance(vec[0], list):
                vec = vec[0]
            return vec
        else:
            vector = self._client.embed_query(text)
            if vector:
                self._dimension = len(vector)
            return vector

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量转向量的别名方法。"""
        return self.embed(texts)

    async def embed_query_async(self, text: str) -> list[float]:
        """embed_query 的异步版本（线程池中执行，避免阻塞事件循环）。"""
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.embed_query, text)

    async def embed_async(self, texts: list[str]) -> list[list[float]]:
        """embed 的异步版本（线程池中执行）。"""
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.embed, texts)


# ------------------------------------------------------------------
# 全局单例
# ------------------------------------------------------------------

_embedding_manager_instances: dict[tuple[str, str, str], EmbeddingManager] = {}
_em_lock = __import__("threading").Lock()


def get_embedding_manager(provider: str | None = None) -> EmbeddingManager:
    """获取 Embedding 管理器；省略 provider 时读取 ``ai.embedding``。"""
    if provider is None:
        settings = get_embedding_settings()
    else:
        settings = {
            "provider": provider,
            "model": PROVIDER_EMBEDDING_MODELS.get(provider, LOCAL_EMBEDDING_MODEL),
            "base_url": PROVIDER_EMBEDDING_URLS.get(provider, ""),
            "api_key": "",
        }

    provider_name = settings["provider"]
    cache_key = (
        provider_name,
        settings.get("model", ""),
        settings.get("base_url", ""),
    )
    if cache_key not in _embedding_manager_instances:
        with _em_lock:
            if cache_key not in _embedding_manager_instances:
                _embedding_manager_instances[cache_key] = EmbeddingManager(
                    provider=provider_name,
                    api_key=settings.get("api_key") or None,
                    base_url=settings.get("base_url") or None,
                    model=settings.get("model") or None,
                )
    return _embedding_manager_instances[cache_key]


def reset_embedding_managers() -> None:
    """丢弃缓存实例，使保存新的 Embedding 配置后可以重新初始化。"""
    with _em_lock:
        _embedding_manager_instances.clear()
