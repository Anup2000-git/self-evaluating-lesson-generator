from evaluator_svc.settings import EvaluatorSettings
from lessongen_common.service import serve

if __name__ == "__main__":
    serve("evaluator_svc.main:app", EvaluatorSettings())
