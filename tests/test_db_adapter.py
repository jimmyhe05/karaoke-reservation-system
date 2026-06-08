from services.db import _postgres_placeholders, _split_sql_statements


def test_postgres_placeholder_translation():
    query = "SELECT * FROM reservations WHERE room_id = ? AND date = ?"

    assert _postgres_placeholders(query) == (
        "SELECT * FROM reservations WHERE room_id = %s AND date = %s"
    )


def test_split_sql_statements_ignores_comments_and_empty_lines():
    script = """
    -- comment
    CREATE TABLE one (id INTEGER);

    CREATE INDEX idx_one_id ON one(id);
    """

    assert _split_sql_statements(script) == [
        "    CREATE TABLE one (id INTEGER)",
        "    CREATE INDEX idx_one_id ON one(id)",
    ]
