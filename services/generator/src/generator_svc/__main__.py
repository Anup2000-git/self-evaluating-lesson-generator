from generator_svc.settings import GeneratorSettings
from lessongen_common.service import serve

if __name__ == "__main__":
    serve("generator_svc.main:app", GeneratorSettings())
