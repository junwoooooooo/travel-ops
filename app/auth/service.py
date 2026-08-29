from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.schemas import UserCreate
from app.core.security import hash_password, verify_password


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, user_id: int) -> User | None:
    return await db.get(User, user_id)


async def create_user(db: AsyncSession, payload: UserCreate) -> User | None:
    """이미 쓰는 이메일이면 None. HTTP 상태코드 결정은 router 몫이다."""
    if await get_by_email(db, payload.email) is not None:
        return None

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        # 위 조회와 commit 사이에 같은 이메일이 끼어든 경우 (unique 제약이 최종 방어선)
        await db.rollback()
        return None
    await db.refresh(user)
    return user


async def authenticate(db: AsyncSession, email: str, password: str) -> User | None:
    user = await get_by_email(db, email)
    if user is None or not verify_password(password, user.hashed_password):
        return None
    return user
