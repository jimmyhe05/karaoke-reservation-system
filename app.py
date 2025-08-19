from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from datetime import datetime, timedelta
import os
import sqlite3
from flask import g
import json

app = Flask(__name__)
app.secret_key = os.urandom(24)

TAX_RATE = 0.055
DATABASE = 'karaoke.db'

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
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


def init_db():
    """Initialize the database if it doesn't exist."""
    db = get_db()

    # Create main tables if they don't exist
    if not os.path.exists(DATABASE):
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()


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

# --- URL Date Path Converter (MM-DD-YYYY) ---
from werkzeug.routing import BaseConverter

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


def parse_time_safe(time_str):
    """
    Safely parse time strings, including those in 24+ hour format (e.g., "25:00").
    Returns a tuple of (datetime object, is_extended_format)
    """
    try:
        # Try standard format first
        return datetime.strptime(time_str, '%H:%M'), False
    except ValueError:
        # Handle extended format (24+ hours)
        if ':' in time_str:
            hours, minutes = time_str.split(':')
            if int(hours) >= 24:
                # Create a time for the equivalent hour on the same day
                # (e.g., "25:00" becomes "01:00")
                normalized_hour = int(hours) % 24
                normalized_time_str = f"{normalized_hour:02d}:{minutes}"
                return datetime.strptime(normalized_time_str, '%H:%M'), True
        # If we can't parse it, re-raise the exception
        raise


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
    db = get_db()
    room = db.execute('SELECT hourly_rate, peak_hour_rate FROM rooms WHERE id = ?', [
                      room_id]).fetchone()

    # Convert times to hours for calculation
    start_hour = int(start_time.split(':')[0])
    end_hour = int(end_time.split(':')[0])

    # Handle overnight reservations (end time already in 24+ hour format or after midnight)
    if end_hour < start_hour:
        end_hour += 24

    total_cost = 0
    current_hour = start_hour

    while current_hour < end_hour:
        # Normalize hour for rate calculation (handle hours > 24)
        normalized_hour = current_hour % 24

        # Different rate periods:
        # Early Bird (11 AM - 6 PM): hourly_rate
        # Prime Time (6 PM - 9 PM): peak_hour_rate
        # Late Night (9 PM - 1 AM): peak_hour_rate
        if 11 <= normalized_hour < 18:  # 11 AM - 6 PM
            rate = room['hourly_rate']
        elif 18 <= normalized_hour < 21:  # 6 PM - 9 PM
            rate = room['peak_hour_rate']
        else:  # 9 PM - 1 AM or 21-25
            rate = room['peak_hour_rate']

        total_cost += rate
        current_hour += 1

    return total_cost


def get_rooms_with_reservations(selected_date=None):
    """Get all rooms with their reservations for the specified date or today."""
    conn = get_db()

    # Use the selected date or default to today
    if selected_date is None:
        selected_date = datetime.now().strftime('%Y-%m-%d')

    # Get all rooms
    rooms = conn.execute('SELECT * FROM rooms').fetchall()

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
        'SELECT COUNT(*) as count FROM rooms').fetchone()['count']
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
    selected_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
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

            if error_fields:
                return jsonify({
                    'error': 'Missing required fields',
                    'fields': error_fields
                }), 400

            # Validate date and time
            try:
                # Parse date and times
                date = datetime.strptime(form_data['date'], '%Y-%m-%d').date()

                # Use our safe time parsing function
                start_time_obj, _ = parse_time_safe(form_data['start_time'])
                end_time_obj, is_extended = parse_time_safe(
                    form_data['end_time'])

                # Extract time components
                start_time = start_time_obj.time()
                end_time = end_time_obj.time()

                # Create datetime objects for comparison
                start_datetime = datetime.combine(date, start_time)
                end_datetime = datetime.combine(date, end_time)

                # Handle overnight reservations
                if is_extended or end_time <= start_time:
                    end_datetime = end_datetime + timedelta(days=1)

                # Check if the date is in the past
                if date < datetime.now().date():
                    error_fields.append('date')

                # Check business hours (11 AM to 1 AM next day)
                business_start = datetime.combine(
                    date, datetime.strptime('11:00', '%H:%M').time())
                business_end = datetime.combine(
                    date + timedelta(days=1), datetime.strptime('01:00', '%H:%M').time())

                # Ensure start time is at least 11 AM and end time is at most 1 AM next day
                if start_datetime < business_start or end_datetime > business_end:
                    error_fields.extend(['start_time', 'end_time'])

                if error_fields:
                    return jsonify({
                        'error': 'Invalid reservation time. Please ensure your reservation is within business hours (11 AM - 1 AM).',
                        'fields': error_fields
                    }), 400

                # Update form_data with datetime objects
                form_data['start_time'] = start_datetime.strftime('%H:%M')

                # For overnight reservations, store end time as 24-hour format (e.g., "25:00" for 1 AM next day)
                if end_time <= start_time:
                    # Convert end time to 24+ hour format for overnight reservations
                    end_hour = end_time.hour + 24
                    form_data['end_time'] = f"{end_hour:02d}:{end_time.minute:02d}"
                else:
                    form_data['end_time'] = end_datetime.strftime('%H:%M')

            except ValueError as e:
                return jsonify({
                    'error': 'Invalid date or time format. Please use HH:MM format for times.',
                    'fields': ['date', 'start_time', 'end_time']
                }), 400

            conn = get_db()
            try:
                # Check if the room is available
                # First, get all reservations that might conflict
                potential_conflicts = conn.execute('''
                    SELECT r.* FROM reservations r
                    WHERE r.room_id = ? AND r.date = ? AND
                    ((r.start_time <= ? AND r.end_time > ?) OR
                     (r.start_time < ? AND r.end_time >= ?) OR
                     (r.start_time >= ? AND r.end_time <= ?))
                ''', (form_data['room_id'], form_data['date'],
                      form_data['start_time'], form_data['start_time'],
                      form_data['end_time'], form_data['end_time'],
                      form_data['start_time'], form_data['end_time'])).fetchall()

                # Check if any of these reservations are NOT in the idle area
                conflict_exists = False
                for res in potential_conflicts:
                    # Check if this reservation is in the idle area
                    idle_check = conn.execute('''
                        SELECT * FROM idle_reservations
                        WHERE reservation_id = ? AND date = ?
                    ''', (res['id'], form_data['date'])).fetchone()

                    # If it's not in the idle area, we have a conflict
                    if not idle_check:
                        conflict_exists = True
                        break

                if conflict_exists:
                    return jsonify({
                        'error': 'Room is not available for the selected time',
                        'fields': ['room_id']
                    }), 400

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
        start_time = data.get('start_time', existing_reservation['start_time'])
        end_time = data.get('end_time', existing_reservation['end_time'])
        room_id = data.get('room_id', existing_reservation['room_id'])
        date = data.get('date', existing_reservation['date'])

        # Check for conflicts with other reservations (excluding the current one)
        # Only check for conflicts if time or room has changed
        if (start_time != existing_reservation['start_time'] or
            end_time != existing_reservation['end_time'] or
            room_id != existing_reservation['room_id'] or
                date != existing_reservation['date']):

            # Log the conflict check parameters
            print(f"Checking conflicts for reservation {reservation_id}:")
            print(f"  Room: {room_id}, Date: {date}")
            print(f"  Time: {start_time} - {end_time}")

            # Improved conflict detection query
            # For debugging, let's print all reservations in this room on this date
            all_reservations = conn.execute('''
                SELECT id, start_time, end_time FROM reservations
                WHERE room_id = ? AND date = ?
            ''', (room_id, date)).fetchall()

            print(f"All reservations in room {room_id} on {date}:")
            for res in all_reservations:
                print(
                    f"  ID: {res['id']}, Time: {res['start_time']} - {res['end_time']}")

            # Now check for conflicts
            conflict = conn.execute('''
                SELECT * FROM reservations
                WHERE room_id = ? AND date = ? AND id != ? AND
                NOT (end_time <= ? OR start_time >= ?)
            ''', (room_id, date, reservation_id,
                  start_time, end_time)).fetchone()

            # Log the conflict check for debugging
            if conflict:
                print(
                    f"Conflict detected for reservation {reservation_id}: {conflict['id']} ({conflict['start_time']} - {conflict['end_time']})")
                print(f"Attempted time: {start_time} - {end_time}")

            if conflict:
                return jsonify({
                    'error': 'The selected time slot is already occupied by another reservation',
                    'conflict': True
                }), 409

        # Calculate new cost if time or room has changed
        if (start_time != existing_reservation['start_time'] or
            end_time != existing_reservation['end_time'] or
                room_id != existing_reservation['room_id']):
            total_cost = calculate_cost(start_time, end_time, room_id)
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
        ''', (room_id, date, start_time, end_time,
              contact_name, contact_phone, contact_email,
              num_people, language, notes, status, total_cost,
              reservation_id))

        conn.commit()
        return jsonify({
            'success': True,
            'message': 'Reservation updated successfully',
            'reservation': {
                'id': reservation_id,
                'room_id': room_id,
                'date': date,
                'start_time': start_time,
                'end_time': end_time,
                'contact_name': contact_name,
                'contact_phone': contact_phone,
                'contact_email': contact_email,
                'num_people': num_people,
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

        conn = get_db()
        try:
            # Get existing reservation
            reservation = conn.execute('SELECT * FROM reservations WHERE id = ?', (reservation_id,)).fetchone()
            if not reservation:
                return jsonify({'error': 'Reservation not found'}), 404

            # Parse old times to preserve duration
            old_start_dt, _ = parse_time_safe(reservation['start_time'])
            old_end_dt, old_is_extended = parse_time_safe(reservation['end_time'])

            # Compute old duration in minutes
            if old_is_extended or old_end_dt <= old_start_dt:
                old_end_dt = old_end_dt.replace(day=old_start_dt.day + 1)
            duration_minutes = int((old_end_dt - old_start_dt).total_seconds() / 60)

            # Parse new start_time provided (HH:MM)
            try:
                new_start_dt = datetime.strptime(start_time_str, '%H:%M')
            except ValueError:
                return jsonify({'error': 'Invalid start_time format. Use HH:MM.'}), 400

            # Determine new end time by adding duration
            new_end_dt = new_start_dt + timedelta(minutes=duration_minutes)

            # If new_end_dt crosses midnight, represent end_time in 24+ hour format (e.g., 25:00)
            # Compare day values
            if new_end_dt.day != new_start_dt.day:
                # compute hour beyond 24
                end_hour = new_end_dt.hour + 24
                new_end_time_str = f"{end_hour:02d}:{new_end_dt.minute:02d}"
            else:
                new_end_time_str = new_end_dt.strftime('%H:%M')

            new_start_time_str = new_start_dt.strftime('%H:%M')

            # Conflict check: ensure no overlapping non-idle reservations
            conflict = conn.execute('''
                SELECT * FROM reservations
                WHERE room_id = ? AND date = ? AND id != ? AND
                NOT (end_time <= ? OR start_time >= ?)
            ''', (room_id, date, reservation_id, new_start_time_str, new_end_time_str)).fetchone()

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
        'SELECT COUNT(*) as count FROM rooms').fetchone()['count']
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
        rooms = conn.execute('SELECT id FROM rooms').fetchall()
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
    print("Received price estimate request:", data)  # Debug log

    try:
        # Parse the times using our safe parser
        start_time, _ = parse_time_safe(data['start_time'])
        end_time, is_extended = parse_time_safe(data['end_time'])

        # Initialize cost components
        room_rate = 0
        period_charges = []

        # Calculate time period charges
        current_time = start_time
        end_datetime = end_time

        # Handle overnight reservations
        if is_extended or end_datetime <= current_time or end_time.hour == 0:
            end_datetime += timedelta(days=1)

        while current_time < end_datetime:
            hour = current_time.hour
            if 11 <= hour < 18:  # 11 AM - 6 PM
                rate = 35
                period = "Early Bird (11 AM - 6 PM)"
            elif 18 <= hour < 21:  # 6 PM - 9 PM
                rate = 45
                period = "Prime Time (6 PM - 9 PM)"
            else:  # 9 PM - 1 AM
                rate = 50
                period = "Late Night (9 PM - 1 AM)"

            # Calculate duration for this rate period
            next_hour = (current_time + timedelta(hours=1)).replace(minute=0)
            if hour >= 21:  # Late night period
                # For late night, ensure we go up to 1 AM (next day)
                next_hour = min(next_hour, (current_time +
                                timedelta(days=1)).replace(hour=1, minute=0))
            # Special handling for midnight (0:00)
            elif hour == 0:  # Midnight
                # Treat midnight as part of the late night period
                next_hour = min(
                    next_hour, (current_time).replace(hour=1, minute=0))

            period_end = min(next_hour, end_datetime)
            duration = (period_end - current_time).total_seconds() / 3600

            period_cost = rate * duration
            room_rate += period_cost

            period_charges.append({
                'time': period,
                'rate': rate,
                'duration': round(duration, 2),
                'cost': round(period_cost, 2)
            })

            current_time = period_end

        # Calculate tax and total
        subtotal = room_rate
        tax = subtotal * TAX_RATE
        total = subtotal + tax

        response_data = {
            'room_rate': round(room_rate, 2),
            'period_charges': period_charges,
            'tax': round(tax, 2),
            'total': round(total, 2)
        }
        print("Price estimate response:", response_data)  # Debug log
        return jsonify(response_data)
    except Exception as e:
        print("Price estimate error:", str(e))  # Debug log
        return jsonify({'error': str(e)}), 400


@app.route('/api/room_suggestion', methods=['POST'])
def room_suggestion():
    data = request.get_json()
    try:
        num_people = int(data['num_people'])

        conn = get_db()
        rooms = conn.execute('SELECT * FROM rooms').fetchall()

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
    app.run(debug=True, port=5007)
