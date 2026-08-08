import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.responses import RedirectResponse

from app.api.api import api_router
from app.settings import settings
from app.utils.breaker import bot_breaker
from app.utils.cache import cache

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMITING_FREQUENCY],
    enabled=settings.RATE_LIMITING_ENABLE,
)
app = FastAPI(title="Transfermarkt API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.include_router(api_router)


@app.middleware("http")
async def conditional_get(request: Request, call_next):
    """
    Answer with 304 Not Modified when the client already holds the cached representation.

    Cached responses carry an ETag derived from the payload, so repeat callers can revalidate
    without transferring the body again.

    Args:
        request (Request): The incoming request.
        call_next: The next handler in the middleware chain.

    Returns:
        Response: The handler's response, or a bodyless 304.
    """
    response = await call_next(request)

    etag = response.headers.get("etag")
    if not etag or request.method not in ("GET", "HEAD") or response.status_code != 200:
        return response

    candidates = [tag.strip() for tag in request.headers.get("if-none-match", "").split(",") if tag.strip()]
    if etag not in candidates and "*" not in candidates:
        return response

    passthrough = ("etag", "cache-control", "x-cache", "age")
    headers = {name: response.headers[name] for name in passthrough if name in response.headers}
    return Response(status_code=304, headers=headers)


@app.get("/", include_in_schema=False)
def docs_redirect():
    """Redirect the site root to the interactive API docs."""
    return RedirectResponse(url="/docs")


@app.get("/health", include_in_schema=False)
def health():
    """
    Report cache effectiveness and whether Transfermarkt is currently blocking scrapes.

    Returns:
        dict: Cache counters and circuit breaker state.
    """
    return {
        "status": "ok",
        "cache": {"enabled": settings.CACHE_ENABLE, **cache.stats()},
        "botBreaker": {
            "open": bot_breaker.is_open,
            "retryAfter": bot_breaker.retry_after,
        },
    }


if __name__ == "__main__":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Adjust this to specify allowed origins
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
