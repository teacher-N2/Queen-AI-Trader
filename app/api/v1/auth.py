from fastapi import APIRouter, Depends

from ...config import settings
from ...platform.dependencies import require_authenticated_principal
from ...platform.schemas import LoginRequest, LoginResponse, envelope
from ...platform.services import user_service

router = APIRouter()


@router.post("/login", summary="Login with email and password")
def login(payload: LoginRequest):
    _, token = user_service.login(email=payload.email, password=payload.password)
    return envelope(LoginResponse(access_token=token, expires_in_minutes=settings.access_token_expire_minutes).model_dump())


@router.get("/me", summary="Return the current authenticated principal")
def me(principal=Depends(require_authenticated_principal)):
    return envelope(principal.model_dump(mode="json"))
