from functools import wraps
from flask import jsonify, request, session


def api_error(message: str, status: int = 400, code=None, fields=None, details=None):
    """Consistent error envelope for JSON APIs."""
    payload = {"error": {"message": message}}
    if code:
        payload["error"]["code"] = code
    if fields:
        payload["error"]["fields"] = fields
    if details:
        payload["error"]["details"] = details
    return jsonify(payload), status


def api_ok(data=None, message=None, status: int = 200):
    payload = {}
    if message:
        payload["message"] = message
    if data is not None:
        payload.update(data)
    return jsonify(payload), status


def request_payload():
    """Return request data without raising on non-JSON content types."""
    data = request.get_json(silent=True)
    if data is not None:
        return data
    if request.form:
        return request.form.to_dict()
    return {}


def require_role(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = session.get('role', 'guest')
            if role not in roles:
                if role == 'guest':
                    return api_error('Admin authentication required', 401, code='auth_required')
                return api_error('Forbidden', 403, code='forbidden')
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def require_admin(fn):
    return require_role('admin')(fn)
