from werkzeug.routing import BaseConverter
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from datetime import datetime, timedelta
import sqlite3
from flask import g
import json
import click
from werkzeug.exceptions import HTTPException

from config import Config
from services.validation import (
    parse_time_safe,
    time_to_minutes,
    normalize_time_range,
    find_conflict,
    slots_overlap,
)


app = Flask(__name__)
app.config.from_object(Config)

if not app.config['SECRET_KEY']:
    raise RuntimeError("SECRET_KEY must be set (see .env)")

TAX_RATE = app.config['TAX_RATE']
DATABASE = app.config['DATABASE']

# Business hours: 11 AM to 1 AM
OPEN_HOUR = 11
CLOSE_HOUR = 1

# Add these constants at the top of the file
ROOMS = [
    {'id': 1, 'name': 'Room 1'},
    {'id': 2, 'name': 'Room 2'},
    {'id': 3, 'name': 'Room 3'}
]


def get_db():
    """Get a database connection."""
    if 'db' not in g:
        db_path = app.config.get('DATABASE', DATABASE)
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row
        # Enforce foreign keys and use WAL for better concurrency on SQLite
        g.db.execute('PRAGMA foreign_keys = ON;')
        g.db.execute('PRAGMA journal_mode = WAL;')
    return g.db


def init_db():
    """Initialize the database schema and indexes (idempotent)."""
    db = get_db()
    with app.open_resource('schema.sql', mode='r') as f:
        db.cursor().executescript(f.read())
    db.commit()


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
        total_cost = calculate_cost(s['start_time'], s['end_time'], s['room_id'])
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
def close_db(error):
    """Close the database connection."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


app.teardown_appcontext(close_db)

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
        return jsonify({'error': description}), code
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
    """
    Compute subtotal, tax, and total for a reservation using room rates.

    - Uses room.hourly_rate for 11:00-18:00
    - Uses room.peak_hour_rate for 18:00-25:00 (6 PM - 1 AM)
    - Supports minute-level durations and overnight via 24+ hour end times.
    Returns dict with subtotal, tax, total, and period_charges breakdown.
    """
    room = conn.execute(
        'SELECT hourly_rate, peak_hour_rate FROM rooms WHERE id = ?', (room_id,)
    ).fetchone()
    if not room:
        raise ValueError('Invalid room id for pricing')

    start_minutes = time_to_minutes(start_time_str)
    end_minutes = time_to_minutes(end_time_str)

    if end_minutes <= start_minutes:
        raise ValueError('End time must be after start time for pricing')

    # Boundaries in minutes from midnight
    EARLY_START = 11 * 60      # 11:00
    EARLY_END = 18 * 60        # 18:00
    PRIME_END = 21 * 60        # 21:00
    LATE_END = 25 * 60         # 01:00 next day (25:00)

    current = start_minutes
    subtotal = 0.0
    period_charges = []

    while current < end_minutes:
        if current < EARLY_END:
            rate = room['hourly_rate']
            period_label = 'Early (11 AM - 6 PM)'
            period_end = min(end_minutes, EARLY_END)
        elif current < PRIME_END:
            rate = room['peak_hour_rate']
            period_label = 'Prime (6 PM - 9 PM)'
            period_end = min(end_minutes, PRIME_END)
        else:
            rate = room['peak_hour_rate']
            period_label = 'Late (9 PM - 1 AM)'
            period_end = min(end_minutes, LATE_END)

        duration_hours = (period_end - current) / 60.0
        cost = rate * duration_hours
        subtotal += cost
        period_charges.append({
            'time': period_label,
            'rate': rate,
            'duration': round(duration_hours, 2),
            'cost': round(cost, 2)
        })

        current = period_end

    tax = round(subtotal * TAX_RATE, 2)
    total = round(subtotal + tax, 2)

    return {
        'subtotal': round(subtotal, 2),
        'tax': tax,
        'total': total,
        'period_charges': period_charges
    }


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
    # Reuse unified pricing; return subtotal (pre-tax) to keep existing DB semantics.
    pricing = compute_pricing(get_db(), room_id, start_time, end_time)
    return pricing['subtotal']


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
            SELECT id, start_time, end_time, contact_name, num_people, language
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
                'language': res['language']
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


def get_today_stats():
    """Get today's reservation statistics."""
    conn = get_db()
    today = datetime.now().strftime('%Y-%m-%d')

    total_reservations = conn.execute('''
        SELECT COUNT(*) as count
        FROM reservations
        WHERE date = ?
    ''', (today,)).fetchone()['count']

    total_rooms = conn.execute(
        'SELECT COUNT(*) as count FROM rooms WHERE id > 0').fetchone()['count']
    total_hours = 14  # 11 AM to 1 AM = 14 hours
    total_room_hours = total_rooms * total_hours

    occupied_hours = conn.execute('''
        SELECT SUM(
            CAST(
                (julianday(end_time) - julianday(start_time)) * 24
                AS INTEGER)
        ) as hours
        FROM reservations
        WHERE date = ?
    ''', (today,)).fetchone()['hours'] or 0

    occupancy_rate = round((occupied_hours / total_room_hours) * 100, 1)

    return {
        'total_reservations': total_reservations,
        'occupancy_rate': occupancy_rate
    }


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
                           today_stats=get_today_stats())


@app.route('/reservation', methods=['GET', 'POST'])
def reservation():
    if request.method == 'POST':
        try:
            # Get data from JSON request
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No data provided'}), 400

            form_data = {
                'date': data.get('date'),
                'start_time': data.get('start_time'),
                'end_time': data.get('end_time'),
                'num_people': data.get('num_people'),
                'contact_name': data.get('contact_name'),
                'contact_phone': data.get('contact_phone'),
                'contact_email': data.get('contact_email'),
                'room_id': data.get('room_id'),
                'language': data.get('language')
            }

            error_fields = []

            # Validate required fields
            if not form_data['contact_name']:
                error_fields.append('contact_name')
            if not form_data['contact_phone']:
                error_fields.append('contact_phone')

            # Validate numeric inputs early
            try:
                form_data['room_id'] = int(form_data['room_id'])
            except Exception:
                error_fields.append('room_id')

            try:
                form_data['num_people'] = int(form_data['num_people'])
            except Exception:
                error_fields.append('num_people')

            if error_fields:
                return jsonify({
                    'error': 'Missing required fields',
                    'fields': error_fields
                }), 400

            # Validate date and time
            try:
                normalized_start, normalized_end, start_minutes, end_minutes = normalize_time_range(
                    form_data['date'], form_data['start_time'], form_data['end_time'])
                form_data['start_time'] = normalized_start
                form_data['end_time'] = normalized_end

            except ValueError as e:
                return jsonify({
                    'error': str(e),
                    'fields': ['date', 'start_time', 'end_time']
                }), 400

            conn = get_db()
            try:
                # Capacity check
                room = conn.execute(
                    'SELECT capacity FROM rooms WHERE id = ?', (form_data['room_id'],)
                ).fetchone()
                if not room:
                    return jsonify({'error': 'Invalid room selected', 'fields': ['room_id']}), 400

                if form_data['num_people'] <= 0 or form_data['num_people'] > room['capacity']:
                    return jsonify({
                        'error': f"Number of people must be between 1 and {room['capacity']}",
                        'fields': ['num_people']
                    }), 400

                # Conflict check
                conflict = find_conflict(
                    conn,
                    form_data['room_id'],
                    form_data['date'],
                    form_data['start_time'],
                    form_data['end_time']
                )

                if conflict:
                    return jsonify({
                        'error': 'Room is not available for the selected time',
                        'fields': ['room_id', 'start_time', 'end_time'],
                        'conflict_with': conflict['id']
                    }), 409

                # Check if the room is available
                # First, get all reservations that might conflict
                # Calculate cost
                total_cost = calculate_cost(
                    form_data['start_time'], form_data['end_time'], form_data['room_id'])

                # Create new reservation
                conn.execute('''
                    INSERT INTO reservations
                    (date, start_time, end_time, num_people,
                     contact_name, contact_phone, contact_email, room_id,
                     total_cost, language)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (form_data['date'], form_data['start_time'],
                      form_data['end_time'], form_data['num_people'],
                      form_data['contact_name'], form_data['contact_phone'],
                      form_data['contact_email'], form_data['room_id'],
                      total_cost, form_data['language']))

                conn.commit()
                return jsonify({'message': 'Reservation created successfully'}), 200

            except Exception as e:
                conn.rollback()
                return jsonify({'error': str(e)}), 500
            finally:
                conn.close()

        except Exception as e:
            return jsonify({'error': str(e)}), 400

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

        # Delete the reservation
        conn.execute('DELETE FROM reservations WHERE id = ?',
                     (reservation_id,))
        conn.commit()

        return jsonify({'message': 'Reservation deleted successfully', 'id': reservation_id}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/update_reservation/<int:reservation_id>', methods=['POST'])
def update_reservation(reservation_id):
    data = request.get_json()
    conn = get_db()
    print(f"Updating reservation {reservation_id} with data: {data}")

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

        room = conn.execute('SELECT capacity FROM rooms WHERE id = ?', (room_id,)).fetchone()
        if not room:
            return jsonify({'error': 'Invalid room id', 'fields': ['room_id']}), 400
        if num_people_int <= 0 or num_people_int > room['capacity']:
            return jsonify({
                'error': f"Number of people must be between 1 and {room['capacity']}",
                'fields': ['num_people']
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
                ''', (room_id, date, normalized_start, normalized_end,
                            contact_name, contact_phone, contact_email,
                            num_people_int, language, notes, status, total_cost,
              reservation_id))

        conn.commit()
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
            return jsonify({'message': 'Reservation already in idle area'}), 200

        # Add to idle_reservations
        conn.execute('''
            INSERT INTO idle_reservations (reservation_id, date)
            VALUES (?, ?)
        ''', (reservation_id, reservation['date']))

        conn.commit()
        return jsonify({'success': True}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/remove_from_idle/<int:reservation_id>', methods=['POST'])
def remove_from_idle(reservation_id):
    """Remove a reservation from the idle area."""
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
        return jsonify({'success': True}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/move_reservation', methods=['POST'])
def move_reservation():
    """Move a reservation to a different room or time slot."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        reservation_id = data.get('reservation_id')
        room_id = data.get('room_id')
        start_time_str = data.get('start_time')  # expected HH:MM
        date = data.get('date')

        if not all([reservation_id, room_id, start_time_str, date]):
            return jsonify({'error': 'Missing required fields'}), 400

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

            # Conflict check: ensure no overlapping non-idle reservations
            conflict = find_conflict(
                conn,
                room_id,
                date,
                new_start_time_str,
                new_end_time_str,
                exclude_id=reservation_id
            )

            if conflict:
                return jsonify({'error': 'The selected time slot is already occupied', 'conflict': True}), 409

            # Update reservation
            conn.execute('''
                UPDATE reservations
                SET room_id = ?, start_time = ?, end_time = ?, date = ?
                WHERE id = ?
            ''', (room_id, new_start_time_str, new_end_time_str, date, reservation_id))
            conn.commit()

            return jsonify({'message': 'Reservation moved successfully', 'reservation': {
                'id': reservation_id,
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

    occupied_hours = conn.execute('''
        SELECT SUM(
            CAST(
                (julianday(end_time) - julianday(start_time)) * 24
                AS INTEGER)
        ) as hours
        FROM reservations
        WHERE date = ?
    ''', (today,)).fetchone()['hours'] or 0

    occupancy_rate = round((occupied_hours / total_room_hours) * 100, 1)

    conn.close()

    return jsonify({
        'total_reservations': total_reservations,
        'occupancy_rate': occupancy_rate
    })


@app.route('/api/room_availability')
def check_room_availability():
    date = request.args.get('date')
    if not date:
        return jsonify({'error': 'Date parameter is required'}), 400

    try:
        date_obj = datetime.strptime(date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400

    conn = get_db()
    try:
        # Get all rooms
        rooms = conn.execute('SELECT id FROM rooms WHERE id > 0').fetchall()
        room_ids = [room['id'] for room in rooms]

        # Get booked rooms for the date
        booked_rooms = conn.execute('''
            SELECT DISTINCT room_id
            FROM reservations
            WHERE date = ?
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
        # Get reservation count for this date
        reservation_count = conn.execute('''
            SELECT COUNT(*) as count
            FROM reservations
            WHERE date = ? AND status != 'cancelled'
        ''', (date,)).fetchone()['count']

        # Get unique booked rooms for this date
        booked_rooms = conn.execute('''
            SELECT COUNT(DISTINCT room_id) as count
            FROM reservations
            WHERE date = ? AND status != 'cancelled'
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
    data = request.get_json()
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
    data = request.get_json()
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
    data = request.get_json()
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


if __name__ == '__main__':
    app.run(debug=True)
