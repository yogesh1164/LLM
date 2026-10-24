"""Cookie account API; all mutations require exact Origin and CSRF checks."""
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select

from app import accounts
from app import database as db
from app.auth_foundation import COOKIE_NAME, token_digest
from app.config import settings
from app.ownership import current_principal

router = APIRouter(prefix="/api/auth", tags=["authentication"])


def cookie_name():
    return COOKIE_NAME if settings.app_env == "production" else "agentflow_session_dev"


def cookie(response, token=None):
    options = {"secure": settings.app_env == "production", "httponly": True,
               "samesite": "strict", "path": "/"}
    if token:
        response.set_cookie(cookie_name(), token, max_age=43200, **options)
    else:
        response.delete_cookie(cookie_name(), **options)
    response.headers["Cache-Control"] = "no-store"


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login: str = Field(max_length=254)
    password: SecretStr = Field(max_length=128)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: SecretStr = Field(max_length=128)
    new_password: SecretStr = Field(min_length=15, max_length=128)


@router.get("/mode")
def mode():
    return {"mode": settings.auth_mode}


@router.post("/login")
def login(body: Credentials, request: Request, response: Response):
    if settings.auth_mode != "accounts":
        raise HTTPException(404, "Not found")
    # Custom header + exact Origin prevents login CSRF, including simple form POSTs.
    if (request.headers.get("origin") not in settings.allowed_frontend_origins
            or request.headers.get("x-agentflow-login") != "1"):
        raise HTTPException(403, "Request verification failed")
    token, csrf, principal = accounts.login(body.login, body.password.get_secret_value())
    prior = request.cookies.get(cookie_name())
    if prior and len(prior) <= 128:
        accounts.revoke(prior)
    cookie(response, token)
    return {"id": str(principal.user_id), "role": principal.role, "csrf_token": csrf}


@router.get("/me")
def me(request: Request):
    principal = current_principal.get()
    if principal is None:
        raise HTTPException(401, "Authentication required")
    with db.SessionLocal() as session:
        name = session.scalar(select(accounts.User.login).where(accounts.User.id == principal.user_id))
    return {"id": str(principal.user_id), "login": name, "role": principal.role,
            "csrf_token": token_digest("csrf:" + request.cookies[cookie_name()])}


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response):
    accounts.revoke(request.cookies[cookie_name()])
    cookie(response)


@router.post("/password", status_code=204)
def password(body: PasswordChange, response: Response):
    accounts.change_password(current_principal.get(), body.current_password.get_secret_value(),
                             body.new_password.get_secret_value())
    cookie(response)
