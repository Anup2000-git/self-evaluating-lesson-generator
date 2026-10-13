from knowledge_svc.settings import KnowledgeSettings
from lessongen_common.service import serve

if __name__ == "__main__":
    serve("knowledge_svc.main:app", KnowledgeSettings())
