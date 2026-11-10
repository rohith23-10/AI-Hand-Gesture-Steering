import pytest

from database import Database


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


def test_tables_exist(db):
    with db._connect() as conn:
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"Users", "Settings", "Game_Sessions"} <= names


def test_create_and_get_user(db):
    uid = db.create_user("rohit", "r@example.com")
    user = db.get_user(uid)
    assert user["username"] == "rohit" and user["email"] == "r@example.com"
    assert user["created_at"]


def test_duplicate_username_rejected(db):
    db.create_user("rohit")
    with pytest.raises(ValueError):
        db.create_user("rohit")


def test_default_user_is_created_once(db):
    assert db.get_or_create_default_user() == db.get_or_create_default_user()


def test_default_settings(db):
    uid = db.get_or_create_default_user()
    s = db.get_settings(uid)
    assert s["steering_sensitivity"] == 1.0
    assert s["acceleration_gesture"] == "open_palm" and s["brake_gesture"] == "fist"


def test_save_settings_roundtrip(db):
    uid = db.get_or_create_default_user()
    db.save_settings(uid, steering_sensitivity=1.8, dead_zone=0.08, brake_gesture="open_palm",
                     acceleration_gesture="fist")
    s = db.get_settings(uid)
    assert s["steering_sensitivity"] == 1.8 and s["dead_zone"] == 0.08
    assert s["brake_gesture"] == "open_palm" and s["acceleration_gesture"] == "fist"


def test_save_unknown_setting_rejected(db):
    uid = db.get_or_create_default_user()
    with pytest.raises(ValueError):
        db.save_settings(uid, nonsense=1)


def test_record_and_list_sessions(db):
    uid = db.get_or_create_default_user()
    db.record_session(uid, "Traffic Racer", 62.456, 14)
    db.record_session(uid, "Euro Truck", 10, 2)
    sessions = db.list_sessions(uid)
    assert [s["game_name"] for s in sessions] == ["Euro Truck", "Traffic Racer"]
    assert sessions[1]["session_duration"] == 62.46 and sessions[1]["steering_events"] == 14


def test_sessions_are_per_user(db):
    a = db.create_user("a")
    b = db.create_user("b")
    db.record_session(a, "G", 1, 1)
    assert db.list_sessions(b) == []


def test_session_for_missing_user_is_rejected(db):
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        db.record_session(999, "G", 1, 1)
