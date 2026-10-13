from lessongen_common.service import serve
from memory_svc.settings import MemorySettings

if __name__ == "__main__":
    serve("memory_svc.main:app", MemorySettings())
