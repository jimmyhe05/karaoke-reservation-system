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

    # Create idle reservations table
    with app.open_resource('idle_schema.sql', mode='r') as f:
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
    return (11.0 <= normalized_start <= 25.0 and
            11.0 <= normalized_end <= 25.0)


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
    if end_hour <= 1:  # Handle after midnight
        end_hour += 24

    total_cost = 0
    current_hour = start_hour

    while current_hour < end_hour:
        # Peak hours are 6 PM (18:00) to 1 AM (25:00)
        rate = room['peak_hour_rate'] if current_hour >= 18 else room['hourly_rate']
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
                start_time = datetime.strptime(
                    reservation['start_time'], '%H:%M')
                end_time = datetime.strptime(reservation['end_time'], '%H:%M')
                duration = (end_time - start_time).total_seconds() / \
                    3600  # in hours

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
                start_time = datetime.strptime(
                    reservation['start_time'], '%H:%M')
                end_time = datetime.strptime(reservation['end_time'], '%H:%M')
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

    # Get all rooms
    rooms = db.execute('''
        SELECT id, name, capacity FROM rooms ORDER BY capacity
    ''').fetchall()

    # Get idle reservations for this date
    idle_reservations_ids = db.execute('''
        SELECT reservation_id FROM idle_reservations
        WHERE date = ?
    ''', [date]).fetchall()

    # Create a set of idle reservation IDs for faster lookup
    idle_reservation_ids_set = {row['reservation_id']
                                for row in idle_reservations_ids}

    result = {'rooms': []}

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

            start_hour = int(res['start_time'].split(':')[0])
            end_hour = int(res['end_time'].split(':')[0])
            if end_hour <= 1:  # Handle after midnight
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
    # Get the selected date from query parameters or use today
    selected_date = request.args.get(
        'date', datetime.now().strftime('%Y-%m-%d'))

    # Get rooms with reservations for the selected date
    data = get_rooms_with_reservations(selected_date)

    return render_template('reservation.html',
                           rooms=data['rooms'],
                           idle_reservations=data['idle_reservations'],
                           selected_date=selected_date,
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
                start_time = datetime.strptime(
                    form_data['start_time'], '%H:%M').time()
                end_time = datetime.strptime(
                    form_data['end_time'], '%H:%M').time()

                # Create datetime objects for comparison
                start_datetime = datetime.combine(date, start_time)
                end_datetime = datetime.combine(date, end_time)

                # Handle overnight reservations
                if end_time <= start_time:
                    end_datetime = end_datetime + timedelta(days=1)

                # Check if the date is in the past
                if date < datetime.now().date():
                    error_fields.append('date')

                # Check business hours (11 AM to 1 AM next day)
                business_start = datetime.combine(
                    date, datetime.strptime('11:00', '%H:%M').time())
                business_end = datetime.combine(
                    date + timedelta(days=1), datetime.strptime('01:00', '%H:%M').time())

                if start_datetime < business_start or end_datetime > business_end:
                    error_fields.extend(['start_time', 'end_time'])

                if error_fields:
                    return jsonify({
                        'error': 'Invalid reservation time. Please ensure your reservation is within business hours (11 AM - 1 AM).',
                        'fields': error_fields
                    }), 400

                # Update form_data with datetime objects
                form_data['start_time'] = start_datetime.strftime('%H:%M')
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

    # GET request handling
    selected_date = request.args.get(
        'date', datetime.now().strftime('%Y-%m-%d'))
    data = get_rooms_with_reservations(selected_date)

    return render_template('reservation.html',
                           rooms=data['rooms'],
                           idle_reservations=data['idle_reservations'],
                           selected_date=selected_date,
                           today_stats=get_today_stats())


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
        'room_id': reservation['room_id']
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

        # Delete the reservation
        conn.execute('DELETE FROM reservations WHERE id = ?',
                     (reservation_id,))
        conn.commit()

        return jsonify({'message': 'Reservation deleted successfully'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/update_reservation/<int:reservation_id>', methods=['POST'])
def update_reservation(reservation_id):
    data = request.get_json()
    conn = get_db()

    try:
        # Check if we need to update the time
        if 'start_time' in data and 'end_time' in data:
            # Calculate new duration and total cost
            start_time = data['start_time']
            end_time = data['end_time']
            room_id = data.get('room_id')

            # If room_id is not provided, get it from the reservation
            if not room_id:
                room_id = conn.execute(
                    'SELECT room_id FROM reservations WHERE id = ?',
                    (reservation_id,)).fetchone()['room_id']

            # Calculate new cost
            total_cost = calculate_cost(start_time, end_time, room_id)

            # Update the reservation time and cost
            conn.execute('''
                UPDATE reservations
                SET start_time = ?, end_time = ?, total_cost = ?
                WHERE id = ?
            ''', (start_time, end_time, total_cost, reservation_id))

        # If room_id is provided, update it
        if 'room_id' in data:
            conn.execute('''
                UPDATE reservations
                SET room_id = ?
                WHERE id = ?
            ''', (data['room_id'], reservation_id))

        conn.commit()
        return jsonify({'success': True}), 200
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
        hour = data.get('hour')
        date = data.get('date')

        if not all([reservation_id, room_id, hour, date]):
            return jsonify({'error': 'Missing required fields'}), 400

        # Convert hour to integer
        hour = int(hour)

        conn = get_db()
        try:
            # Get the existing reservation
            reservation = conn.execute(
                'SELECT * FROM reservations WHERE id = ?', (reservation_id,)).fetchone()

            if not reservation:
                return jsonify({'error': 'Reservation not found'}), 404

            # Calculate new start and end times
            old_start_time = datetime.strptime(
                reservation['start_time'], '%H:%M')
            old_end_time = datetime.strptime(reservation['end_time'], '%H:%M')

            # Calculate duration in hours
            duration_hours = 0
            if old_end_time < old_start_time:  # Overnight reservation
                old_end_time_adjusted = old_end_time.replace(
                    day=old_start_time.day + 1)
                duration = old_end_time_adjusted - old_start_time
            else:
                duration = old_end_time - old_start_time

            duration_hours = duration.total_seconds() / 3600

            # Create new start and end times
            new_start_time = f"{hour:02d}:00"
            new_end_hour = (hour + int(duration_hours)) % 24
            new_end_time = f"{new_end_hour:02d}:00"

            # Check if the new time slot is available
            conflict = conn.execute('''
                SELECT * FROM reservations
                WHERE room_id = ? AND date = ? AND id != ? AND
                ((start_time <= ? AND end_time > ?) OR
                 (start_time < ? AND end_time >= ?) OR
                 (start_time >= ? AND end_time <= ?))
            ''', (room_id, date, reservation_id,
                  new_start_time, new_start_time,
                  new_end_time, new_end_time,
                  new_start_time, new_end_time)).fetchone()

            if conflict:
                return jsonify({
                    'error': 'The selected time slot is already occupied',
                    'conflict': True
                }), 409

            # Update the reservation
            conn.execute('''
                UPDATE reservations
                SET room_id = ?, start_time = ?, end_time = ?, date = ?
                WHERE id = ?
            ''', (room_id, new_start_time, new_end_time, date, reservation_id))

            conn.commit()

            return jsonify({
                'message': 'Reservation moved successfully',
                'reservation': {
                    'id': reservation_id,
                    'room_id': room_id,
                    'start_time': new_start_time,
                    'end_time': new_end_time,
                    'date': date
                }
            }), 200

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


@app.route('/api/price_estimate', methods=['POST'])
def price_estimate():
    data = request.get_json()
    print("Received price estimate request:", data)  # Debug log

    try:
        # Parse the times using datetime
        start_time = datetime.strptime(data['start_time'], '%H:%M')
        end_time = datetime.strptime(data['end_time'], '%H:%M')

        # Initialize cost components
        room_rate = 0
        period_charges = []

        # Calculate time period charges
        current_time = start_time
        end_datetime = end_time

        # Handle overnight reservations
        if end_datetime <= current_time:
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
                next_hour = min(next_hour, (current_time +
                                timedelta(days=1)).replace(hour=1, minute=0))
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
    app.run(debug=True)
