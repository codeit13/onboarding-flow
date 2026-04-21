from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/backend/api/users", tags=["users"])


def _base_user(email: str):
    return {
        "email": email,
        "fullname": "",
        "bots": [],
        "roles": []
    }


@router.get("/search/email")
async def search_user_by_email(email: str = Query(...)):
    """
    Lookup a user by exact email.
    Returns a minimal user object so the frontend renders without crashing.
    Extend this if you add a real user store later.
    """
    return JSONResponse(content=_base_user(email))


@router.get("/search/email-prefix")
async def search_users_by_email_prefix(emailPrefix: str = Query(...)):
    """
    Search users whose email starts with the given prefix.
    Returns an empty list until a real user store is wired up.
    """
    return JSONResponse(content=[])


@router.post("/save")
async def save_user(body: dict):
    """
    Persist a new user.
    Returns the payload back as a no-op until a real user store is wired up.
    """
    return JSONResponse(content=body)
