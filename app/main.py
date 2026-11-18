"""FastAPI entry point: run with `uvicorn app.main:app --reload`."""

from fastapi import Depends, FastAPI, Header, HTTPException, status

from app import __version__
from app.config import Settings, get_settings
from app.schemas import HealthResponse, QueryRequest, QueryResponse

app = FastAPI(
    title="Chicago Civic Data Assistant",
    version=__version__,
    description="Answers questions about Chicago from city data tables and city documents, with citations.",
)


def require_api_key(
    x_api_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    if x_api_key != settings.service_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid X-API-Key")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(version=__version__)


@app.post("/query", response_model=QueryResponse, dependencies=[Depends(require_api_key)])
def query(req: QueryRequest) -> QueryResponse:
    # TODO (Day 6): call app.answer.answer(req.question) and return its result
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Pipeline not built yet")
