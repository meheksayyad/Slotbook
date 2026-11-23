from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse


def health(request):
    """Liveness + dependency check used by Docker/K8s probes."""
    status = {"database": "ok", "cache": "ok"}
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception:  # noqa: BLE001
        status["database"] = "down"
    try:
        cache.set("health", "1", 5)
        if cache.get("health") != "1":
            raise RuntimeError
    except Exception:  # noqa: BLE001
        status["cache"] = "down"
    code = 200 if all(v == "ok" for v in status.values()) else 503
    return JsonResponse(status, status=code)
