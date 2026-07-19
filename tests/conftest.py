import pytest

from bot.storage.user_store import UserStore


@pytest.fixture
def store(tmp_path):
    return UserStore(str(tmp_path / "heracles-test.db"))


@pytest.fixture
def active_user(store):
    user_id = "user-1"
    store.upsert_user(user_id, "Test User")
    store.update_user_status(user_id, "active")
    return user_id
