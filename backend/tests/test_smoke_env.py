from sqlalchemy import text

from app.core.db import get_engine


def test_runs_against_test_database_only(db):
    assert db.execute(text("select current_database()")).scalar() == "beforeyougo_test"
    assert db.execute(text("select count(*) from events")).scalar() == 0
    assert str(get_engine().url).endswith("/beforeyougo_test")
