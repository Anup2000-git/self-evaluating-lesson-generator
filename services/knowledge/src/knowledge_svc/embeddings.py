"""Optional dense retrieval with an Azure OpenAI embeddings deployment.

Only activated when AZURE_OPENAI_EMBEDDING_DEPLOYMENT is set; otherwise every pack keeps
its BM25 retriever. A failure to build embeddings degrades to BM25 instead of failing
startup - search quality drops a little, but lessons stay grounded.
"""

from __future__ import annotations

from pathlib import Path

from knowledge_svc.packs import PackRegistry
from knowledge_svc.retriever import BM25Retriever, DenseRetriever, HybridRetriever
from lessongen_common.llm import LLMSettings
from lessongen_common.logs import get_logger

log = get_logger(__name__)


async def attach_dense_retrievers(
    registry: PackRegistry, settings: LLMSettings, cache_dir: Path | None
) -> None:
    deployment = settings.azure_openai_embedding_deployment.strip()
    if not deployment or not settings.configured:
        return
    from langchain_openai import AzureOpenAIEmbeddings

    embedder = AzureOpenAIEmbeddings(
        azure_endpoint=settings.azure_openai_endpoint,
        azure_deployment=deployment,
        api_version=settings.azure_openai_api_version,
        api_key=settings.azure_openai_api_key,
    )
    for loaded in registry.packs.values():
        if not isinstance(loaded.retriever, BM25Retriever):
            continue
        dense = DenseRetriever(loaded.chunks, embedder.aembed_query)
        try:
            await dense.build(embedder.aembed_documents, cache_dir, deployment)
        except Exception as exc:
            log.warning(
                "embeddings_unavailable_using_bm25", topic_id=loaded.pack.id, error=str(exc)
            )
            continue
        loaded.retriever = HybridRetriever(loaded.retriever, dense)
        log.info("hybrid_search_enabled", topic_id=loaded.pack.id, deployment=deployment)
