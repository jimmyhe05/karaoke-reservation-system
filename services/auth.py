from werkzeug.security import generate_password_hash, check_password_hash
from services.db import get_db, is_postgres_connection

def create_user(email, password, name, google_id=None, conn=None):
    """Create a new customer user. password can be None for Google OAuth users."""
    passed_conn = conn is not None
    if not passed_conn:
        conn = get_db()
        
    password_hash = None
    if password:
        password_hash = generate_password_hash(password)
        
    email_lower = email.strip().lower()
    
    insert_sql = """
        INSERT INTO users (email, password_hash, name, google_id)
        VALUES (?, ?, ?, ?)
    """
    params = (email_lower, password_hash, name.strip(), google_id)
    
    try:
        if is_postgres_connection(conn):
            cursor = conn.execute(insert_sql.replace("?", "%s") + " RETURNING id", params)
            user_id = cursor.fetchone()["id"]
        else:
            cursor = conn.execute(insert_sql, params)
            user_id = cursor.lastrowid
        conn.commit()
        return get_user_by_id(user_id, conn=conn)
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        if not passed_conn:
            conn.close()

def get_user_by_id(user_id, conn=None):
    passed_conn = conn is not None
    if not passed_conn:
        conn = get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        if not passed_conn:
            conn.close()

def get_user_by_email(email, conn=None):
    passed_conn = conn is not None
    if not passed_conn:
        conn = get_db()
    try:
        email_lower = email.strip().lower()
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email_lower,)).fetchone()
        return dict(row) if row else None
    finally:
        if not passed_conn:
            conn.close()

def get_user_by_google_id(google_id, conn=None):
    passed_conn = conn is not None
    if not passed_conn:
        conn = get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE google_id = ?", (google_id,)).fetchone()
        return dict(row) if row else None
    finally:
        if not passed_conn:
            conn.close()

def verify_user(email, password, conn=None):
    """Verify email & password credentials. Returns user dict if valid, else None."""
    passed_conn = conn is not None
    if not passed_conn:
        conn = get_db()
    try:
        user = get_user_by_email(email, conn=conn)
        if not user or not user.get("password_hash"):
            return None
        if check_password_hash(user["password_hash"], password):
            return user
        return None
    finally:
        if not passed_conn:
            conn.close()
