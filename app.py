from werkzeug.routing import BaseConverter
from flask import Flask, render_template, request, redirect, url_for, jsonify, abort, session
from datetime import datetime, timedelta
from flask import g
import json
import click
import logging
import uuid
from werkzeug.exceptions import HTTPException

from config import Config
from services.db import get_db, init_db, close_db
from services.validation import (
    parse_time_safe,
    normalize_time_range,
    find_conflict,
    time_to_minutes,
)
from services.validation import slots_overlap  # noqa: F401 (re-export for tests)
from services.pricing import compute_pricing as compute_pricing_service, calculate_cost as calculate_cost_service
from services.reservations import (
    serialize_reservation_row,
    validate_room_capacity,
    is_blackout,
    create_reservation_api_payload,
    log_action,
    record_reservation_history,
    get_today_stats,
)
from routes.api import api_bp
from services.http import api_error, api_ok, request_payload


app = Flask(__name__)
app.config.from_object(Config)
app.register_blueprint(api_bp)


def _json_formatter(record):
    base = {
        "time": datetime.utcnow().isoformat() + "Z",
        "level": record.levelname,
        "message": record.getMessage(),
    }
    # Attach request context if available
    try:
        base["path"] = request.path
        base["method"] = request.method
        base["request_id"] = getattr(g, 'request_id', None)
    except RuntimeError:
        pass
    return json.dumps(base)


class JsonLogFormatter(logging.Formatter):
    def format(self, record):
        return _json_formatter(record)


def configure_logging(flask_app: Flask):
    """Configure logging; default to JSON for API friendliness."""
    level_name = flask_app.config.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    log_format = flask_app.config.get("LOG_FORMAT", "json")

    if not flask_app.logger.handlers:
        handler = logging.StreamHandler()
        if log_format == "json":
            formatter = JsonLogFormatter()
        else:
            formatter = logging.Formatter('[%(asctime)s] %(levelname)s %(message)s')
        handler.setFormatter(formatter)
        flask_app.logger.addHandler(handler)

    flask_app.logger.setLevel(level)


configure_logging(app)


def validate_security_config(flask_app: Flask):
    """Fail closed in production when unsafe placeholder credentials are active."""
    if not flask_app.config['SECRET_KEY']:
        raise RuntimeError("SECRET_KEY must be set (see .env)")
    if flask_app.config.get('TESTING'):
        return

    weak_values = {
        'SECRET_KEY': {'dev-change-me', 'change-me', 'change-me-in-prod', 'karaoke'},
        'ADMIN_PASSWORD': {'admin', 'password', 'change-me', 'change-me-in-prod'},
        'STAFF_PASSWORD': {'staff', 'password', 'change-me', 'change-me-in-prod'},
    }
    weak_keys = [
        key for key, placeholders in weak_values.items()
        if str(flask_app.config.get(key, '')).strip() in placeholders
    ]
    if not weak_keys:
        return

    message = (
        "Unsafe placeholder configuration detected for "
        f"{', '.join(weak_keys)}. Update .env before deploying."
    )
    if flask_app.config.get('APP_ENV') in {'prod', 'production'}:
        raise RuntimeError(message)
    flask_app.logger.warning(message)


validate_security_config(app)

TAX_RATE = app.config['TAX_RATE']
DATABASE = app.config['DATABASE']

# Business hours: 11 AM to 1 AM
OPEN_HOUR = 11
CLOSE_HOUR = 1

ROOMS = [
    {'id': 1, 'name': 'Room 1'},
    {'id': 2, 'name': 'Room 2'},
    {'id': 3, 'name': 'Room 3'}
]


@app.before_request
def attach_request_metadata():
    """Attach a request id for traceable logs."""
    request.request_id = request.headers.get('X-Request-ID', str(uuid.uuid4()))
    g.request_id = request.request_id


# ---- Auth helpers ----


def is_worker_authenticated():
    return session.get('role') in {'admin', 'staff'}


def seed_sample_data(target_date=None):
    """Seed a few sample reservations if none exist for the target date."""
    conn = get_db()
    if target_date is None:
        target_date = datetime.now().strftime('%Y-%m-%d')

    existing = conn.execute(
        'SELECT COUNT(*) as c FROM reservations WHERE date = ?', (target_date,)
    ).fetchone()['c']
    if existing:
        return False, f"Reservations already exist for {target_date}; skipping seed"

    samples = [
        {
            'room_id': 1,
            'start_time': '13:00',
            'end_time': '15:00',
            'contact_name': 'Sample Guest 1',
            'contact_phone': '555-0100',
            'num_people': 4,
            'language': 'en',
            'notes': 'Seed demo',
        },
        {
            'room_id': 2,
            'start_time': '18:30',
            'end_time': '20:00',
            'contact_name': 'Sample Guest 2',
            'contact_phone': '555-0111',
            'num_people': 6,
            'language': 'en',
            'notes': 'Seed demo',
        },
        {
            'room_id': 3,
            'start_time': '21:00',
            'end_time': '23:00',
            'contact_name': 'Sample Guest 3',
            'contact_phone': '555-0122',
            'num_people': 3,
            'language': 'en',
            'notes': 'Seed demo',
        },
    ]

    for s in samples:
        total_cost = calculate_cost_service(get_db(), s['room_id'], s['start_time'], s['end_time'], TAX_RATE)
        conn.execute(
            '''INSERT INTO reservations
               (room_id, date, start_time, end_time, contact_name, contact_phone,
                contact_email, num_people, language, status, total_cost, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, ?)''',
            (
                s['room_id'],
                target_date,
                s['start_time'],
                s['end_time'],
                s['contact_name'],
                s['contact_phone'],
                '',
                s['num_people'],
                s['language'],
                total_cost,
                s['notes'],
            )
        )
    conn.commit()
    return True, f"Seeded {len(samples)} reservations for {target_date}"


@app.teardown_appcontext
def _close_db(error):
    close_db(error)


# Initialize the database only if it doesn't exist
with app.app_context():
    init_db()


# ---- Error Handling ----


@app.errorhandler(Exception)
def handle_exception(e):
    """Return JSON for API routes; fall back to default HTML otherwise."""
    is_api = request.path.startswith('/api/')

    if isinstance(e, HTTPException):
        code = e.code
        description = e.description
    else:
        code = 500
        description = 'Internal server error'

    if is_api:
        return api_error(description, status=code, code='exception')
    return e

# ---- CLI Commands ----


@app.cli.command("init-db")
def init_db_command():
    """Initialize the database schema (idempotent)."""
    init_db()
    click.echo("Initialized the database.")


@app.cli.command("seed-sample")
@click.option('--date', default=None, help='YYYY-MM-DD date to seed (defaults to today)')
def seed_sample_command(date):
    """Seed sample reservations if none exist for the given date."""
    ok, message = seed_sample_data(date)
    click.echo(message)
    if not ok:
        # non-fatal; communicate via exit code 0
        return

# --- URL Date Path Converter (MM-DD-YYYY) ---


class DatePathConverter(BaseConverter):
    regex = r'\d{2}-\d{2}-\d{4}'


app.url_map.converters['datepath'] = DatePathConverter


def normalize_date_path(date_str):
    """Convert MM-DD-YYYY to YYYY-MM-DD or raise ValueError."""
    try:
        dt = datetime.strptime(date_str, '%m-%d-%Y').date()
        return dt.strftime('%Y-%m-%d')
    except ValueError:
        raise


def compute_pricing(conn, room_id, start_time_str, end_time_str):
    return compute_pricing_service(conn, room_id, start_time_str, end_time_str, TAX_RATE)


def is_within_business_hours(start_time, end_time):
    """Check if the reservation falls within business hours (11 AM - 1 AM next day)."""
    # If end time is before start time, it means it's crossing midnight
    if end_time < start_time:
        end_time = end_time + timedelta(days=1)

    # Convert times to the same day for comparison
    normalized_start = start_time.hour + start_time.minute / 60
    normalized_end = end_time.hour + end_time.minute / 60
    if normalized_end < normalized_start:  # If end time is next day
        normalized_end += 24

    # Business hours: 11 AM (11.0) to 1 AM next day (25.0)
    # Start time must be at least 11 AM
    # End time must be at most 1 AM next day (25.0 in normalized time)
    # End time must be after start time (already handled by the normalization above)
    return (11.0 <= normalized_start < 25.0 and
            11.0 < normalized_end <= 25.0)


def is_room_available(room_id, start_time, end_time, exclude_id=None):
    """Check if the room is available for the given time slot."""
    db = get_db()
    query = '''
        SELECT * FROM reservations
        WHERE room_id = ?
        AND ((? < end_time) AND (? > start_time))
    '''
    params = [room_id, end_time.isoformat(), start_time.isoformat()]

    if exclude_id is not None:
        query += ' AND id != ?'
        params.append(exclude_id)

    existing_reservations = db.execute(query, params).fetchall()
    return len(existing_reservations) == 0


def calculate_cost(start_time, end_time, room_id):
    pricing = compute_pricing_service(get_db(), room_id, start_time, end_time, TAX_RATE)
    return pricing['total']


def get_rooms_with_reservations(selected_date=None):
    """Get all rooms with their reservations for the specified date or today."""
    conn = get_db()

    # Use the selected date or default to today
    if selected_date is None:
        selected_date = datetime.now().strftime('%Y-%m-%d')

    # Get all bookable rooms (exclude idle placeholder if present)
    rooms = conn.execute('SELECT * FROM rooms WHERE id > 0 ORDER BY id').fetchall()

    # Get reservations for the selected date
    reservations = conn.execute('''
        SELECT * FROM reservations
        WHERE date = ?
        ORDER BY start_time
    ''', (selected_date,)).fetchall()

    # Get idle reservations for the selected date
    idle_reservations_ids = conn.execute('''
        SELECT reservation_id FROM idle_reservations
        WHERE date = ?
    ''', (selected_date,)).fetchall()

    idle_reservation_ids_set = {row['reservation_id']
                                for row in idle_reservations_ids}

    # Organize reservations by room
    rooms_with_reservations = []
    for room in rooms:
        room_reservations = []
        for reservation in reservations:
            # Skip reservations that are in the idle area
            if reservation['id'] in idle_reservation_ids_set:
                continue

            if reservation['room_id'] == room['id']:
                # Calculate start hour and duration for display
                start_time, _ = parse_time_safe(reservation['start_time'])
                end_time, is_extended = parse_time_safe(
                    reservation['end_time'])

                # For overnight reservations, add a day to end_time for correct duration calculation
                if is_extended or end_time <= start_time:
                    end_time_with_day = end_time.replace(
                        day=start_time.day + 1)
                    duration = (end_time_with_day -
                                start_time).total_seconds() / 3600  # in hours
                else:
                    # in hours
                    duration = (end_time - start_time).total_seconds() / 3600

                room_reservations.append({
                    'id': reservation['id'],
                    'contact_name': reservation['contact_name'],
                    'num_people': reservation['num_people'],
                    'start_time': reservation['start_time'],
                    'end_time': reservation['end_time'],
                    'start_hour': start_time.hour,
                    'duration': duration
                })

        rooms_with_reservations.append({
            'id': room['id'],
            'name': room['name'],
            'reservations': room_reservations
        })

    # Get idle reservations details
    idle_reservations = []
    if idle_reservations_ids:
        idle_res_list = ', '.join(['?' for _ in idle_reservations_ids])
        idle_res_ids = [row['reservation_id'] for row in idle_reservations_ids]

        if idle_res_ids:
            idle_res_data = conn.execute(f'''
                SELECT * FROM reservations
                WHERE id IN ({idle_res_list})
            ''', idle_res_ids).fetchall()

            for reservation in idle_res_data:
                start_time, _ = parse_time_safe(reservation['start_time'])
                end_time, is_extended = parse_time_safe(
                    reservation['end_time'])

                # For overnight reservations, add a day to end_time for correct duration calculation
                if is_extended or end_time <= start_time:
                    end_time_with_day = end_time.replace(
                        day=start_time.day + 1)
                    duration = (end_time_with_day -
                                start_time).total_seconds() / 3600  # in hours
                else:
                    # in hours
                    duration = (end_time - start_time).total_seconds() / 3600

                idle_reservations.append({
                    'id': reservation['id'],
                    'contact_name': reservation['contact_name'],
                    'num_people': reservation['num_people'],
                    'start_time': reservation['start_time'],
                    'end_time': reservation['end_time'],
                    'start_hour': start_time.hour,
                    'duration': duration,
                    'room_id': reservation['room_id']
                })

    return {
        'rooms': rooms_with_reservations,
        'idle_reservations': idle_reservations
    }


@app.route('/api/daily_reservations')
def get_daily_reservations():
    date = request.args.get('date')
    if not date:
        return jsonify({'error': 'Date parameter is required'}), 400

    db = get_db()

    # Get all rooms (excluding the idle room with id=0)
    rooms = db.execute('''
        SELECT id, name, capacity FROM rooms WHERE id > 0 ORDER BY capacity
    ''').fetchall()

    # Get idle reservations for this date
    idle_reservations_ids = db.execute('''
        SELECT reservation_id FROM idle_reservations
        WHERE date = ?
    ''', [date]).fetchall()

    # Create a set of idle reservation IDs for faster lookup
    idle_reservation_ids_set = {row['reservation_id']
                                for row in idle_reservations_ids}

    result = {'rooms': [], 'idle_reservations': []}

    for room in rooms:
        # Get all reservations for this room and date
        reservations = db.execute('''
            SELECT id, start_time, end_time, contact_name, num_people, language, notes
            FROM reservations
            WHERE room_id = ? AND date = ? AND status != 'cancelled'
            ORDER BY start_time
        ''', [room['id'], date]).fetchall()

        room_data = {
            'id': room['id'],
            'name': room['name'],
            'capacity': room['capacity'],
            'reservations': []
        }

        for res in reservations:
            # Skip reservations that are in the idle area
            if res['id'] in idle_reservation_ids_set:
                continue

            # Use our safe time parsing function
            start_time, _ = parse_time_safe(res['start_time'])
            end_time, is_extended = parse_time_safe(res['end_time'])

            start_hour = start_time.hour
            end_hour = end_time.hour

            # Handle overnight reservations
            if is_extended or end_hour <= start_hour:
                end_hour += 24

            room_data['reservations'].append({
                'id': res['id'],
                'start_time': res['start_time'],
                'end_time': res['end_time'],
                'start_hour': start_hour,
                'duration': end_hour - start_hour,
                'contact_name': res['contact_name'],
                'num_people': res['num_people'],
                'language': res['language'],
                'notes': res['notes']
            })

        result['rooms'].append(room_data)

    # Get all idle reservations for this date
    if idle_reservation_ids_set:
        idle_reservations = db.execute('''
            SELECT id, start_time, end_time, contact_name, num_people, language, room_id, notes
            FROM reservations
            WHERE id IN ({}) AND date = ?
            ORDER BY start_time
        '''.format(','.join(['?'] * len(idle_reservation_ids_set))),
            list(idle_reservation_ids_set) + [date]).fetchall()

        for res in idle_reservations:
            # Use our safe time parsing function
            start_time, _ = parse_time_safe(res['start_time'])
            end_time, is_extended = parse_time_safe(res['end_time'])

            start_hour = start_time.hour
            end_hour = end_time.hour

            # Handle overnight reservations
            if is_extended or end_hour <= start_hour:
                end_hour += 24

            result['idle_reservations'].append({
                'id': res['id'],
                'start_time': res['start_time'],
                'end_time': res['end_time'],
                'start_hour': start_hour,
                'duration': end_hour - start_hour,
                'contact_name': res['contact_name'],
                'num_people': res['num_people'],
                'language': res['language'],
                'room_id': res['room_id'],
                'notes': res['notes']
            })

    return jsonify(result)


# API routes moved to routes/api.py blueprint


@app.route('/')
def index():
    # Redirect root to today's date path
    today_path = datetime.now().strftime('%m-%d-%Y')
    return redirect(f'/{today_path}')


@app.route('/improved')
def improved_reservation():
    # Backward compatibility: redirect to date path
    selected_date = request.args.get(
        'date', datetime.now().strftime('%Y-%m-%d'))
    try:
        dt = datetime.strptime(selected_date, '%Y-%m-%d')
    except ValueError:
        dt = datetime.now()
    return redirect(f"/{dt.strftime('%m-%d-%Y')}")


@app.route('/<datepath:date_str>')
def reservation_by_date(date_str):
    # date_str is MM-DD-YYYY
    try:
        iso_date = normalize_date_path(date_str)
    except ValueError:
        abort(404)
    data = get_rooms_with_reservations(iso_date)
    return render_template('reservation.html',
                           rooms=data['rooms'],
                           idle_reservations=data['idle_reservations'],
                           selected_date=iso_date,
                           today_stats=get_today_stats(get_db()))


@app.route('/reservation', methods=['GET', 'POST'])
def reservation():
    if request.method == 'POST':
        if not is_worker_authenticated():
            return api_error('Worker login required', 401, code='auth_required')
        data = request_payload()
        # Reuse shared validator/creator but keep legacy success message/status for compatibility
        return create_reservation_api_payload(
            data,
            api_error,
            api_ok,
            success_message='Reservation created successfully',
            status_code=200,
            include_success=False,
        )

    # GET request handling - redirect to improved reservation page
    return redirect(url_for('improved_reservation'))


@app.route('/get_reservation/<int:reservation_id>')
def get_reservation(reservation_id):
    conn = get_db()
    reservation = conn.execute(
        'SELECT * FROM reservations WHERE id = ?', (reservation_id,)).fetchone()
    conn.close()

    if reservation is None:
        return jsonify({'error': 'Reservation not found'}), 404

    return jsonify({
        'id': reservation['id'],
        'date': reservation['date'],
        'start_time': reservation['start_time'],
        'end_time': reservation['end_time'],
        'num_people': reservation['num_people'],
        'contact_name': reservation['contact_name'],
        'contact_phone': reservation['contact_phone'],
        'contact_email': reservation['contact_email'],
        'room_id': reservation['room_id'],
        'language': reservation['language'],
        'notes': reservation['notes'],
        'status': reservation['status'],
        'total_cost': reservation['total_cost']
    })


@app.route('/delete_reservation/<int:reservation_id>', methods=['POST'])
def delete_reservation(reservation_id):
    if not is_worker_authenticated():
        return jsonify({'error': 'Worker login required'}), 401
    conn = get_db()
    try:
        # Check if reservation exists
        reservation = conn.execute(
            'SELECT * FROM reservations WHERE id = ?', (reservation_id,)).fetchone()

        if not reservation:
            return jsonify({'error': 'Reservation not found'}), 404

        # Also check if the reservation is in the idle area and remove it if it is
        conn.execute('DELETE FROM idle_reservations WHERE reservation_id = ?',
                     (reservation_id,))

        # Delete history entries first to avoid foreign key violations
        conn.execute('DELETE FROM reservation_history WHERE reservation_id = ?', (reservation_id,))

        # Delete the reservation
        conn.execute('DELETE FROM reservations WHERE id = ?',
                     (reservation_id,))
        conn.commit()

        log_action(
            "reservation.delete",
            reservation_id=reservation_id,
            date=reservation['date'],
            room_id=reservation['room_id'],
        )

        return jsonify({'message': 'Reservation deleted successfully', 'id': reservation_id}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/update_reservation/<int:reservation_id>', methods=['POST'])
def update_reservation(reservation_id):
    if not is_worker_authenticated():
        return jsonify({'error': 'Worker login required'}), 401
    data = request_payload()
    conn = get_db()

    try:
        # Get the existing reservation to fill in any missing fields
        existing_reservation = conn.execute(
            'SELECT * FROM reservations WHERE id = ?',
            (reservation_id,)).fetchone()

        if not existing_reservation:
            return jsonify({'error': 'Reservation not found'}), 404

        # Extract time and room data for conflict checking
        start_time_raw = data.get('start_time', existing_reservation['start_time'])
        end_time_raw = data.get('end_time', existing_reservation['end_time'])
        room_id = data.get('room_id', existing_reservation['room_id'])
        date = data.get('date', existing_reservation['date'])

        try:
            room_id = int(room_id)
        except Exception:
            return jsonify({'error': 'Invalid room id', 'fields': ['room_id']}), 400

        # Normalize/validate times
        try:
            normalized_start, normalized_end, _, _ = normalize_time_range(
                date, start_time_raw, end_time_raw)
        except ValueError as e:
            return jsonify({'error': str(e), 'fields': ['start_time', 'end_time', 'date']}), 400

        # Check for conflicts with other reservations (excluding the current one)
        # Only check for conflicts if time or room has changed
        if (normalized_start != existing_reservation['start_time'] or
            normalized_end != existing_reservation['end_time'] or
            room_id != existing_reservation['room_id'] or
                date != existing_reservation['date']):

            # Log the conflict check parameters
            # Now check for conflicts
            conflict = find_conflict(
                conn,
                room_id,
                date,
                normalized_start,
                normalized_end,
                exclude_id=reservation_id
            )

            if conflict:
                return jsonify({
                    'error': 'The selected time slot is already occupied by another reservation',
                    'conflict': True
                }), 409

        # Calculate new cost if time or room has changed
        if (normalized_start != existing_reservation['start_time'] or
            normalized_end != existing_reservation['end_time'] or
                room_id != existing_reservation['room_id']):
            total_cost = calculate_cost(normalized_start, normalized_end, room_id)
        else:
            total_cost = existing_reservation['total_cost']

        # Prepare all fields for update
        contact_name = data.get(
            'contact_name', existing_reservation['contact_name'])
        contact_phone = data.get(
            'contact_phone', existing_reservation['contact_phone'])
        contact_email = data.get(
            'contact_email', existing_reservation['contact_email'])
        num_people = data.get('num_people', existing_reservation['num_people'])
        try:
            num_people_int = int(num_people)
        except Exception:
            return jsonify({'error': 'Invalid number of people', 'fields': ['num_people']}), 400

        ok, msg, room = validate_room_capacity(conn, room_id, num_people_int)
        if not ok:
            return jsonify({
                'error': msg,
                'fields': ['room_id', 'num_people']
            }), 400
        language = data.get('language', existing_reservation['language'])
        notes = data.get('notes', existing_reservation['notes'])
        status = data.get('status', existing_reservation['status'])

        # Update all reservation fields
        conn.execute('''
            UPDATE reservations
            SET room_id = ?, date = ?, start_time = ?, end_time = ?,
                contact_name = ?, contact_phone = ?, contact_email = ?,
                num_people = ?, language = ?, notes = ?, status = ?, total_cost = ?
            WHERE id = ?
                ''', (
                    room_id,
                    date,
                    normalized_start,
                    normalized_end,
                    contact_name,
                    contact_phone,
                    contact_email,
                    num_people_int,
                    language,
                    notes,
                    status,
                    total_cost,
                    reservation_id,
                ))

        conn.commit()

        updated = conn.execute(
            'SELECT * FROM reservations WHERE id = ?', (reservation_id,)
        ).fetchone()
        if updated:
            record_reservation_history(
                conn,
                reservation_id,
                "updated",
                serialize_reservation_row(updated),
            )

        log_action(
            "reservation.update",
            reservation_id=reservation_id,
            room_id=room_id,
            date=date,
            start_time=normalized_start,
            end_time=normalized_end,
            num_people=num_people_int,
            status=status,
        )
        return jsonify({
            'success': True,
            'message': 'Reservation updated successfully',
            'reservation': {
                'id': reservation_id,
                'room_id': room_id,
                'date': date,
                'start_time': normalized_start,
                'end_time': normalized_end,
                'contact_name': contact_name,
                'contact_phone': contact_phone,
                'contact_email': contact_email,
                'num_people': num_people_int,
                'language': language,
                'notes': notes,
                'status': status,
                'total_cost': total_cost
            }
        }), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/move_to_idle/<int:reservation_id>', methods=['POST'])
def move_to_idle(reservation_id):
    """Move a reservation to the idle area."""
    if not is_worker_authenticated():
        return jsonify({'error': 'Worker login required'}), 401
    conn = get_db()
    try:
        # Check if the reservation exists
        reservation = conn.execute(
            'SELECT * FROM reservations WHERE id = ?',
            (reservation_id,)).fetchone()

        if not reservation:
            return jsonify({'error': 'Reservation not found'}), 404

        # Check if it's already in the idle area
        existing = conn.execute(
            'SELECT * FROM idle_reservations WHERE reservation_id = ?',
            (reservation_id,)).fetchone()

        if existing:
            # Already idle — treat as success to avoid client-side failure toasts
            return jsonify({'success': True, 'message': 'Reservation already in idle area'}), 200

        # Add to idle_reservations
        conn.execute('''
            INSERT INTO idle_reservations (reservation_id, date)
            VALUES (?, ?)
        ''', (reservation_id, reservation['date']))

        conn.commit()
        log_action(
            "reservation.idle.move_in",
            reservation_id=reservation_id,
            date=reservation['date'],
            room_id=reservation['room_id'],
        )
        record_reservation_history(
            conn,
            reservation_id,
            "moved_to_idle",
            serialize_reservation_row(reservation, in_idle=True),
        )
        return jsonify({'success': True}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/remove_from_idle/<int:reservation_id>', methods=['POST'])
def remove_from_idle(reservation_id):
    """Remove a reservation from the idle area."""
    if not is_worker_authenticated():
        return jsonify({'error': 'Worker login required'}), 401
    conn = get_db()
    try:
        # Check if the reservation exists in idle area
        existing = conn.execute(
            'SELECT * FROM idle_reservations WHERE reservation_id = ?',
            (reservation_id,)).fetchone()

        if not existing:
            return jsonify({'error': 'Reservation not found in idle area'}), 404

        # Remove from idle_reservations
        conn.execute(
            'DELETE FROM idle_reservations WHERE reservation_id = ?',
            (reservation_id,))

        conn.commit()
        log_action(
            "reservation.idle.remove",
            reservation_id=reservation_id,
            date=existing['date'],
        )
        reservation = conn.execute(
            'SELECT * FROM reservations WHERE id = ?', (reservation_id,)
        ).fetchone()
        if reservation:
            record_reservation_history(
                conn,
                reservation_id,
                "removed_from_idle",
                serialize_reservation_row(reservation, in_idle=False),
            )
        return jsonify({'success': True}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/move_reservation', methods=['POST'])
def move_reservation():
    """Move a reservation to a different room or time slot."""
    if not is_worker_authenticated():
        return jsonify({'error': 'Worker login required'}), 401
    try:
        data = request_payload()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        reservation_id = data.get('reservation_id')
        room_id = data.get('room_id')
        start_time_str = data.get('start_time')  # expected HH:MM
        date = data.get('date')

        if not all([reservation_id, room_id, start_time_str, date]):
            return jsonify({'error': 'Missing required fields'}), 400

        try:
            reservation_id_int = int(reservation_id)
        except Exception:
            return jsonify({'error': 'Invalid reservation id', 'fields': ['reservation_id']}), 400

        try:
            room_id = int(room_id)
        except Exception:
            return jsonify({'error': 'Invalid room id', 'fields': ['room_id']}), 400

        conn = get_db()
        try:
            # Get existing reservation
            reservation = conn.execute(
                'SELECT * FROM reservations WHERE id = ?', (reservation_id,)).fetchone()
            if not reservation:
                return jsonify({'error': 'Reservation not found'}), 404

            # Parse old times to preserve duration
            old_start_dt, _ = parse_time_safe(reservation['start_time'])
            old_end_dt, old_is_extended = parse_time_safe(
                reservation['end_time'])

            # Compute old duration in minutes
            if old_is_extended or old_end_dt <= old_start_dt:
                old_end_dt = old_end_dt.replace(day=old_start_dt.day + 1)
            duration_minutes = int(
                (old_end_dt - old_start_dt).total_seconds() / 60)

            # Normalize new start/end using duration
            try:
                new_start_dt = datetime.strptime(start_time_str, '%H:%M')
            except ValueError:
                return jsonify({'error': 'Invalid start_time format. Use HH:MM.'}), 400

            new_end_dt = new_start_dt + timedelta(minutes=duration_minutes)

            if new_end_dt.day != new_start_dt.day:
                new_end_time_str = f"{new_end_dt.hour + 24:02d}:{new_end_dt.minute:02d}"
            else:
                new_end_time_str = new_end_dt.strftime('%H:%M')

            new_start_time_str = new_start_dt.strftime('%H:%M')

            # Validate business hours and ordering
            try:
                normalize_time_range(date, new_start_time_str, new_end_time_str)
            except ValueError as e:
                return jsonify({'error': str(e), 'fields': ['start_time', 'end_time']}), 400

            blocked, win = is_blackout(date, new_start_time_str, new_end_time_str, room_id)
            if blocked:
                return api_error(
                    'Requested time is unavailable (maintenance/blackout)',
                    409,
                    code='blackout',
                    details={'blackout': win}
                )

            # Conflict check: ensure no overlapping non-idle reservations
            conflict = find_conflict(
                conn,
                room_id,
                date,
                new_start_time_str,
                new_end_time_str,
                exclude_id=reservation_id_int
            )

            if conflict:
                return jsonify({'error': 'The selected time slot is already occupied', 'conflict': True}), 409

            # Update reservation
            conn.execute('''
                UPDATE reservations
                SET room_id = ?, start_time = ?, end_time = ?, date = ?
                WHERE id = ?
            ''', (room_id, new_start_time_str, new_end_time_str, date, reservation_id_int))

            # If this reservation was marked idle, remove the idle flag so it returns to timelines
            conn.execute(
                'DELETE FROM idle_reservations WHERE reservation_id = ? AND date = ?',
                (reservation_id, date)
            )
            conn.commit()

            updated = conn.execute(
                'SELECT * FROM reservations WHERE id = ?', (reservation_id_int,)
            ).fetchone()
            if updated:
                record_reservation_history(
                    conn,
                    reservation_id_int,
                    "moved",
                    serialize_reservation_row(updated),
                )

            log_action(
                "reservation.move",
                reservation_id=reservation_id_int,
                room_id=room_id,
                date=date,
                start_time=new_start_time_str,
                end_time=new_end_time_str,
            )

            return jsonify({'message': 'Reservation moved successfully', 'reservation': {
                'id': reservation_id_int,
                'room_id': room_id,
                'start_time': new_start_time_str,
                'end_time': new_end_time_str,
                'date': date
            }}), 200

        except Exception as e:
            conn.rollback()
            return jsonify({'error': str(e)}), 500
        finally:
            conn.close()
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/today_stats')
def today_stats():
    conn = get_db()
    today = datetime.now().strftime('%Y-%m-%d')

    # Get total reservations for today
    total_reservations = conn.execute('''
        SELECT COUNT(*) as count
        FROM reservations
        WHERE date = ?
    ''', (today,)).fetchone()['count']

    # Calculate occupancy rate
    total_rooms = conn.execute(
        'SELECT COUNT(*) as count FROM rooms WHERE id > 0').fetchone()['count']
    total_hours = 14  # 11 AM to 1 AM = 14 hours
    total_room_hours = total_rooms * total_hours

    reservations = conn.execute(
        '''SELECT start_time, end_time
           FROM reservations
           WHERE date = ? AND status != 'cancelled' ''',
        (today,),
    ).fetchall()
    occupied_hours = sum(
        (time_to_minutes(row['end_time']) - time_to_minutes(row['start_time'])) / 60
        for row in reservations
    )

    occupancy_rate = round((occupied_hours / total_room_hours) * 100, 1)

    conn.close()

    return jsonify({
        'total_reservations': total_reservations,
        'occupancy_rate': occupancy_rate
    })


@app.route('/api/public_schedule')
def public_schedule():
    """Public, anonymized schedule: rooms with time slots only."""
    date = request.args.get('date') or datetime.now().strftime('%Y-%m-%d')
    conn = get_db()

    rooms = conn.execute('SELECT id, name FROM rooms WHERE id > 0 ORDER BY id').fetchall()
    reservations = conn.execute('''
        SELECT id, room_id, start_time, end_time, status
        FROM reservations
        WHERE date = ? AND status != 'cancelled'
        ORDER BY start_time
    ''', (date,)).fetchall()
    idle_ids = conn.execute(
        'SELECT reservation_id FROM idle_reservations WHERE date = ?', (date,)
    ).fetchall()
    idle_set = {row['reservation_id'] for row in idle_ids}

    schedule = []
    for room in rooms:
        room_slots = []
        for res in reservations:
            if res['room_id'] != room['id'] or res['id'] in idle_set:
                continue
            room_slots.append({
                'start_time': res['start_time'],
                'end_time': res['end_time'],
                'status': res['status'],
            })
        schedule.append({
            'room_id': room['id'],
            'room_name': room['name'],
            'reservations': room_slots
        })

    return jsonify({'date': date, 'rooms': schedule})


@app.route('/api/room_availability')
def check_room_availability():
    date = request.args.get('date')
    if not date:
        return jsonify({'error': 'Date parameter is required'}), 400

    try:
        datetime.strptime(date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400

    conn = get_db()
    try:
        # Get all rooms
        rooms = conn.execute('SELECT id FROM rooms WHERE id > 0').fetchall()
        room_ids = [room['id'] for room in rooms]

        # Get booked rooms for the date
        booked_rooms = conn.execute('''
            SELECT DISTINCT r.room_id
            FROM reservations r
            WHERE r.date = ?
              AND r.status != 'cancelled'
              AND NOT EXISTS (
                SELECT 1 FROM idle_reservations i
                WHERE i.reservation_id = r.id AND i.date = r.date
              )
        ''', (date,)).fetchall()
        booked_room_ids = [room['room_id'] for room in booked_rooms]

        # Available rooms are those not in booked_room_ids
        available_rooms = list(set(room_ids) - set(booked_room_ids))

        return jsonify({
            'available_rooms': available_rooms,
            'total_rooms': len(room_ids),
            'booked_rooms': len(booked_room_ids)
        })
    finally:
        conn.close()


@app.route('/api/calendar_availability')
def calendar_availability():
    """Get availability data for the calendar view."""
    start_date = request.args.get('start')
    end_date = request.args.get('end')

    if not start_date or not end_date:
        return jsonify({'error': 'Start and end date parameters are required'}), 400

    try:
        start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400

    conn = get_db()

    # Get total number of rooms
    total_rooms = conn.execute(
        'SELECT COUNT(*) as count FROM rooms WHERE id > 0').fetchone()['count']

    # Calculate date range
    date_range = []
    current_date = start_date_obj
    while current_date <= end_date_obj:
        date_range.append(current_date.strftime('%Y-%m-%d'))
        current_date += timedelta(days=1)

    result = []

    for date in date_range:
        # Exclude reservations placed in idle area for this date
        reservation_count = conn.execute('''
            SELECT COUNT(*) as count
            FROM reservations r
            WHERE r.date = ?
              AND r.status != 'cancelled'
              AND NOT EXISTS (
                SELECT 1 FROM idle_reservations i
                WHERE i.reservation_id = r.id AND i.date = r.date
              )
        ''', (date,)).fetchone()['count']

        # Get unique booked rooms for this date (also excluding idle)
        booked_rooms = conn.execute('''
            SELECT COUNT(DISTINCT r.room_id) as count
            FROM reservations r
            WHERE r.date = ?
              AND r.status != 'cancelled'
              AND NOT EXISTS (
                SELECT 1 FROM idle_reservations i
                WHERE i.reservation_id = r.id AND i.date = r.date
              )
        ''', (date,)).fetchone()['count']

        # Calculate available rooms
        available_rooms = total_rooms - booked_rooms

        # Calculate occupancy percentage
        occupancy_percentage = (
            booked_rooms / total_rooms * 100) if total_rooms > 0 else 0

        # Add to result
        result.append({
            'date': date,
            'reservationCount': reservation_count,
            'availableRooms': available_rooms,
            'totalRooms': total_rooms,
            'occupancyPercentage': round(occupancy_percentage, 1)
        })

    return jsonify(result)


@app.route('/api/price_estimate', methods=['POST'])
def price_estimate():
    data = request_payload()
    try:
        normalized_start, normalized_end, _, _ = normalize_time_range(
            data['date'], data['start_time'], data['end_time'])
    except Exception as e:
        return jsonify({'error': str(e), 'fields': ['date', 'start_time', 'end_time']}), 400

    try:
        pricing = compute_pricing(get_db(), data['room_id'], normalized_start, normalized_end)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

    return jsonify({
        'room_rate': pricing['subtotal'],
        'period_charges': pricing['period_charges'],
        'tax': pricing['tax'],
        'total': pricing['total']
    })


@app.route('/api/room_suggestion', methods=['POST'])
def room_suggestion():
    data = request_payload()
    try:
        num_people = int(data['num_people'])

        conn = get_db()
        rooms = conn.execute('SELECT * FROM rooms WHERE id > 0 ORDER BY id').fetchall()

        # Define room capacity ranges
        small_rooms = [room for room in rooms if room['capacity'] <= 4]
        medium_rooms = [room for room in rooms if 4 < room['capacity'] <= 8]
        large_rooms = [room for room in rooms if room['capacity'] > 8]

        suggested_rooms = []
        reason = ""

        if num_people <= 4:
            suggested_rooms = [room['id'] for room in small_rooms]
            reason = "Perfect for small groups up to 4 people"
        elif num_people <= 8:
            suggested_rooms = [room['id'] for room in medium_rooms]
            reason = "Ideal for medium-sized groups"
        else:
            suggested_rooms = [room['id'] for room in large_rooms]
            reason = "Best suited for large groups"

        return jsonify({
            'suggested_rooms': suggested_rooms,
            'reason': reason
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/alternative_times', methods=['POST'])
def alternative_times():
    data = request_payload()
    try:
        date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        start_time = datetime.strptime(data['start_time'], '%H:%M').time()
        room_id = int(data['room_id'])

        conn = get_db()

        # Get existing reservations for the room on the selected date
        existing_reservations = conn.execute('''
            SELECT start_time, end_time
            FROM reservations
            WHERE room_id = ? AND date = ?
            ORDER BY start_time
        ''', (room_id, date)).fetchall()

        # Generate alternative times
        alternatives = []
        current_time = datetime.strptime('11:00', '%H:%M').time()
        end_time = datetime.strptime('01:00', '%H:%M').time()

        while current_time < end_time:
            # Skip if this time conflicts with existing reservations
            is_available = True
            for reservation in existing_reservations:
                if (current_time >= reservation['start_time'] and
                        current_time < reservation['end_time']):
                    is_available = False
                    break

            if is_available and current_time != start_time:
                alternatives.append(current_time.strftime('%H:%M'))

            # Move to next 30-minute slot
            current_hour = current_time.hour
            current_minute = current_time.minute
            if current_minute == 30:
                current_hour += 1
                current_minute = 0
            else:
                current_minute = 30
            current_time = datetime.strptime(
                f'{current_hour:02d}:{current_minute:02d}', '%H:%M').time()

        return jsonify({
            'alternatives': alternatives[:5]  # Return top 5 alternatives
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# ---- Admin auth routes ----


@app.route('/login', methods=['POST'])
def admin_login():
    data = request_payload()
    username = data.get('username')
    password = data.get('password')
    role = None

    if username == app.config['ADMIN_USERNAME'] and password == app.config['ADMIN_PASSWORD']:
        role = 'admin'
    elif username == app.config.get('STAFF_USERNAME') and password == app.config.get('STAFF_PASSWORD'):
        role = 'staff'

    if role:
        session['role'] = role
        return jsonify({'message': f'Logged in as {role}', 'role': role})

    return api_error('Invalid credentials', 401, code='invalid_credentials')


@app.route('/logout', methods=['POST'])
def admin_logout():
    session.clear()
    return jsonify({'message': 'Logged out'})


@app.route('/api/me')
def current_user():
    role = session.get('role', 'guest')
    return jsonify({
        'is_admin': role == 'admin',
        'role': role,
        'can_manage_reservations': role in {'admin', 'staff'},
    })


if __name__ == '__main__':
    app.run(debug=True)
