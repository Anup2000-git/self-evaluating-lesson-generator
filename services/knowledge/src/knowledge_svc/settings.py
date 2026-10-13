from __future__ import annotations

from pathlib import Path

from lessongen_common.settings import ServiceSettings

PACKAGED_PACKS_DIR = Path(__file__).parent / "packs"


class KnowledgeSettings(ServiceSettings):
    service_port: int = 8003
    packs_dir: Path = PACKAGED_PACKS_DIR
    # Where computed embeddings are cached (only used when an embeddings deployment is set).
    embedding_cache_dir: Path = Path("/tmp/lessongen-embeddings")
    default_k: int = 4
