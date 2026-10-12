"""FastAPI dependencies shared by routers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.services.wiring import Services, get_services


def services_dep() -> Services:
    return get_services()


ServicesDep = Annotated[Services, Depends(services_dep)]
