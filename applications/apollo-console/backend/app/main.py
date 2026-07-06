from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


FRONTEND_DIRECTORY = (
    Path(__file__).resolve().parent.parent
    / "frontend-dist"
)

app = FastAPI(
    title="Apollo Operations Console API",
    version="0.1.0",
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "apollo-console",
        "version": "0.1.0",
    }


app.mount(
    "/",
    StaticFiles(
        directory=FRONTEND_DIRECTORY,
        html=True,
    ),
    name="frontend",
)
