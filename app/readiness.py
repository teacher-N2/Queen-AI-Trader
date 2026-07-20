from .health import health_service


def readiness_snapshot() -> dict:
    return health_service.ready()
