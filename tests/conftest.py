"""テスト用DBセットアップ（各テストで独立したSQLite in-memory DB）"""
import os
import unittest.mock as mock

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from src.main import app
from src.database import get_session

# テスト環境フラグ（pay-testエンドポイントのStripeチェックをバイパス）
os.environ.setdefault("TESTING", "true")

TEST_DB_URL = "sqlite+aiosqlite://"  # in-memory


@pytest.fixture(autouse=True)
def mock_stripe():
    """Stripe APIをモック化（テスト環境では実際の外部API呼び出しを行わない）"""
    mock_intent = mock.MagicMock()
    mock_intent.id = "pi_test_mock_123"
    mock_intent.client_secret = "pi_test_mock_123_secret_abc"

    with mock.patch("stripe.PaymentIntent.create", return_value=mock_intent):
        yield mock_intent


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    TestSession = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with TestSession() as s:
        yield s
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def client(session):
    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
