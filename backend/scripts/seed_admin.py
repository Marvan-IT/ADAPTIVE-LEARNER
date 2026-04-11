"""CLI script to create an admin user directly in the database.

Usage:
    cd backend
    python -m scripts.seed_admin --email admin@school.com --password SecurePass123!

The script is idempotent — running it twice with the same email is a no-op.
Admin users are created with email_verified=True and is_active=True so they
can log in immediately without going through the OTP flow.
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure backend/src is on sys.path, matching the uvicorn / alembic convention.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from auth.models import User
from config import DATABASE_URL

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def main(email: str, password: str) -> None:
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL is not set. Check backend/.env")
        sys.exit(1)

    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        result = await db.execute(select(User).where(User.email == email.lower()))
        existing = result.scalar_one_or_none()
        if existing:
            print(f"Admin user already exists: {email} (role={existing.role})")
            await engine.dispose()
            return

        user = User(
            email=email.lower(),
            password_hash=pwd_context.hash(password),
            role="admin",
            is_active=True,
            email_verified=True,
        )
        db.add(user)
        await db.commit()
        print(f"Admin user created successfully: {email}")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create an admin user for ADA")
    parser.add_argument("--email", required=True, help="Admin email address")
    parser.add_argument("--password", required=True, help="Admin password (min 8 chars)")
    args = parser.parse_args()
    asyncio.run(main(args.email, args.password))
