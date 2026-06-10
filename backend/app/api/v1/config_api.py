"""配置试算端点：前端每步选配后调用，无副作用。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.models import AppUser
from app.schemas.config import ConfigPayload, ValidateResult
from app.services.config_engine import validate_config

router = APIRouter(prefix="/config", tags=["config"])


@router.post("/validate", response_model=ValidateResult)
def validate(
    payload: ConfigPayload,
    db: Session = Depends(get_db),
    _: AppUser = Depends(get_current_user),
) -> ValidateResult:
    result, _name = validate_config(db, payload)
    return result
