from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from email_workshop.foundry import FoundryClassifier, FoundryConfig, FoundryError, required

logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)


class EmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=20000)


class Classification(BaseModel):
    labels: list[str]
    backend: str = "foundry-managed"
    model: str
    # This endpoint never claims that remote prompt specialization is a trained adapter.
    trained_adapter: bool = False


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config = FoundryConfig.from_env()
        token = required("WORKSHOP_API_TOKEN")
        if len(token) < 32 or not token.isascii():
            raise ValueError("WORKSHOP_API_TOKEN must contain at least 32 ASCII characters.")
        app.state.classifier = FoundryClassifier(config)
        app.state.token = token
        yield

    app = FastAPI(
        title="Email workshop — Foundry managed inference",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {key: item[key] for key in ("loc", "msg", "type")} for item in error.errors()
                ]
            },
        )

    def authorize(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> None:
        if credentials is None or not secrets.compare_digest(
            credentials.credentials.encode(), app.state.token.encode()
        ):
            raise HTTPException(
                401, "Invalid or missing API token.", headers={"WWW-Authenticate": "Bearer"}
            )

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/classify", response_model=Classification, dependencies=[Depends(authorize)])
    def classify(email: EmailRequest) -> Classification:
        try:
            labels = app.state.classifier.classify(email.subject, email.body)
        except FoundryError as error:
            logger.warning("Managed classification failed: %s", error)
            raise HTTPException(502, str(error)) from None
        return Classification(labels=labels, model=app.state.classifier.config.model)

    return app
