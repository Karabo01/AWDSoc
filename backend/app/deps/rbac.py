from collections.abc import Callable

from fastapi import Depends, HTTPException, status

from app.deps.auth import CurrentUser
from app.models import User


def require_roles(*roles: str) -> Callable[[User], User]:
    """Route dependency. RBAC lives here, never scattered through handlers."""
    allowed = set(roles)

    def dependency(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your role does not allow this action.",
            )
        return user

    return dependency


require_platform_admin = Depends(require_roles("platform_admin"))
require_staff = Depends(require_roles("platform_admin", "soc_analyst"))
