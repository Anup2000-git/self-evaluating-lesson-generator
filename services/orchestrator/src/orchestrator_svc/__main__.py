"""`python -m orchestrator_svc` runs the API; `python -m orchestrator_svc.worker` runs a worker."""

from lessongen_common.service import serve
from orchestrator_svc.settings import OrchestratorSettings

if __name__ == "__main__":
    serve("orchestrator_svc.main:app", OrchestratorSettings())
