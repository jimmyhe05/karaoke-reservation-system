from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime, timedelta
import os
import sqlite3
from flask import g

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
    """Initialize the database with the schema."""
    db = get_db()
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

# Initialize the database when the app starts
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


def calculate_cost(start_time, end_time):
    """Calculate total karaoke charge based on the time spent in the room."""
    total_cost = 0
    cost_breakdown = []

    # Handle overnight reservations
    if end_time <= start_time:
        end_time = end_time + timedelta(days=1)

    current_time = start_time
    while current_time < end_time:
        # Determine rate period
        if 11 <= current_time.hour < 18:  # 11 AM - 6 PM
            rate = 35
            segment = "Early Bird Special (11 AM - 6 PM)"
        elif 18 <= current_time.hour < 21:  # 6 PM - 9 PM
            rate = 45
            segment = "Prime Time (6 PM - 9 PM)"
        elif 21 <= current_time.hour or current_time.hour < 1:  # 9 PM - 1 AM
            rate = 50
            segment = "Late Night (9 PM - 1 AM)"
        else:  # 1 AM - 11 AM (Closed)
            raise ValueError(
                "Invalid reservation time. For overnight reservations, please ensure your reservation ends by 1 AM. The restaurant is closed from 1 AM to 11 AM.")

        # Calculate until next rate change or reservation end
        next_change = current_time.replace(
            minute=0, second=0, microsecond=0) + timedelta(hours=1)
        if current_time.hour >= 21:  # Handle overnight rates
            next_change = min(next_change, current_time.replace(
                hour=1, minute=0, second=0))
            if current_time < current_time.replace(hour=0, minute=0, second=0):
                next_change = min(next_change, current_time.replace(
                    hour=1, minute=0, second=0))

        segment_end = min(next_change, end_time)
        duration = (segment_end - current_time).total_seconds() / \
            3600  # In hours

        cost_segment = rate * duration
        total_cost += cost_segment

        cost_breakdown.append({
            'period': segment,
            'start': current_time.strftime('%I:%M %p'),
            'end': segment_end.strftime('%I:%M %p'),
            'hours': round(duration, 2),
            'rate': rate,
            'cost': round(cost_segment, 2)
        })

        current_time = segment_end

    total_cost_with_tax = total_cost * (1 + TAX_RATE)
    return round(total_cost_with_tax, 2), cost_breakdown


def get_rooms_with_reservations():
    """Get all rooms with their reservations for the current date."""
    conn = get_db()
    today = datetime.now().strftime('%Y-%m-%d')

    # Get all rooms
    rooms = conn.execute('SELECT * FROM rooms').fetchall()

    # Get reservations for today
    reservations = conn.execute('''
        SELECT * FROM reservations 
        WHERE date = ?
        ORDER BY start_time
    ''', (today,)).fetchall()

    # Organize reservations by room
    rooms_with_reservations = []
    for room in rooms:
        room_reservations = []
        for reservation in reservations:
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

    return rooms_with_reservations


@app.route('/api/daily_reservations')
def get_daily_reservations():
    selected_date = request.args.get(
        'date', datetime.now().strftime('%Y-%m-%d'))

    conn = get_db()
    try:
        # Get all rooms
        rooms = conn.execute('SELECT * FROM rooms').fetchall()

        # Get reservations for the selected date
        reservations = conn.execute('''
            SELECT * FROM reservations 
            WHERE date = ?
            ORDER BY start_time
        ''', (selected_date,)).fetchall()

        # Organize reservations by room
        rooms_with_reservations = []
        for room in rooms:
            room_reservations = []
            for reservation in reservations:
                if reservation['room_id'] == room['id']:
                    # Calculate start hour and duration
                    start_time = datetime.strptime(
                        reservation['start_time'], '%H:%M')
                    end_time = datetime.strptime(
                        reservation['end_time'], '%H:%M')

                    # Handle overnight reservations
                    if end_time < start_time:
                        end_time = end_time + timedelta(days=1)

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

        return jsonify({
            'rooms': rooms_with_reservations,
            'date': selected_date
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/')
def index():
    # Get the selected date from query parameters or use today
    selected_date = request.args.get(
        'date', datetime.now().strftime('%Y-%m-%d'))

    conn = get_db()
    try:
        # Get today's stats
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

        # Get rooms with reservations for the selected date
        rooms = conn.execute('SELECT * FROM rooms').fetchall()
        reservations = conn.execute('''
            SELECT * FROM reservations 
            WHERE date = ?
            ORDER BY start_time
        ''', (selected_date,)).fetchall()

        # Organize reservations by room
        rooms_with_reservations = []
        for room in rooms:
            room_reservations = []
            for reservation in reservations:
                if reservation['room_id'] == room['id']:
                    # Calculate start hour and duration
                    start_time = datetime.strptime(
                        reservation['start_time'], '%H:%M')
                    end_time = datetime.strptime(
                        reservation['end_time'], '%H:%M')

                    # Handle overnight reservations
                    if end_time < start_time:
                        end_time = end_time + timedelta(days=1)

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

        return render_template('reservation.html',
                               rooms=rooms_with_reservations,
                               selected_date=selected_date,
                               today_stats={
                                   'total_reservations': total_reservations,
                                   'occupancy_rate': occupancy_rate
                               })

    finally:
        conn.close()


@app.route('/reservation', methods=['GET', 'POST'])
def reservation():
    if request.method == 'POST':
        form_data = {
            'date': request.form['date'],
            'start_time': request.form['start_time'],
            'end_time': request.form['end_time'],
            'num_people': request.form['num_people'],
            'contact_name': request.form['contact_name'],
            'contact_phone': request.form['contact_phone'],
            'contact_email': request.form['contact_email'],
            'room_id': request.form['room_id']
        }

        error_fields = []

        # Validate contact information
        if not form_data['contact_name'].strip():
            error_fields.append('contact_name')
        if not form_data['contact_phone'].strip():
            error_fields.append('contact_phone')
        if not form_data['contact_email'].strip():
            error_fields.append('contact_email')

        # Validate number of people
        try:
            num_people = int(form_data['num_people'])
            if num_people < 1 or num_people > 20:
                error_fields.append('num_people')
        except ValueError:
            error_fields.append('num_people')

        # Validate date and time
        try:
            date = datetime.strptime(form_data['date'], '%Y-%m-%d').date()
            start_time = datetime.strptime(
                form_data['start_time'], '%H:%M').time()
            end_time = datetime.strptime(form_data['end_time'], '%H:%M').time()

            # Check if the date is in the past
            if date < datetime.now().date():
                error_fields.append('date')

            # Check business hours
            if start_time < datetime.strptime('11:00', '%H:%M').time() or \
               end_time > datetime.strptime('01:00', '%H:%M').time():
                error_fields.append('start_time')
                error_fields.append('end_time')

            # Check if end time is after start time
            if end_time <= start_time:
                # For overnight reservations, add a day to end_time
                end_time = datetime.combine(date + timedelta(days=1), end_time)
            else:
                end_time = datetime.combine(date, end_time)

            start_time = datetime.combine(date, start_time)

        except ValueError:
            error_fields.extend(['date', 'start_time', 'end_time'])

        if error_fields:
            # Get today's stats for the dashboard
            today = datetime.now().strftime('%Y-%m-%d')
            conn = get_db()

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

            occupancy_rate = round(
                (occupied_hours / total_room_hours) * 100, 1)

            return render_template('reservation.html',
                                   rooms=get_rooms_with_reservations(),
                                   error_fields=error_fields,
                                   form_data=form_data,
                                   today_stats={
                                       'total_reservations': total_reservations,
                                       'occupancy_rate': occupancy_rate
                                   })

        conn = get_db()
        try:
            # Check if the room is available
            existing_reservation = conn.execute('''
                SELECT * FROM reservations 
                WHERE room_id = ? AND date = ? AND 
                ((start_time <= ? AND end_time > ?) OR 
                 (start_time < ? AND end_time >= ?) OR 
                 (start_time >= ? AND end_time <= ?))
            ''', (form_data['room_id'], form_data['date'],
                  form_data['start_time'], form_data['start_time'],
                  form_data['end_time'], form_data['end_time'],
                  form_data['start_time'], form_data['end_time'])).fetchone()

            if existing_reservation:
                error_fields.append('room_id')

                # Get today's stats for the dashboard
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

                occupancy_rate = round(
                    (occupied_hours / total_room_hours) * 100, 1)

                return render_template('reservation.html',
                                       rooms=get_rooms_with_reservations(),
                                       error_fields=error_fields,
                                       form_data=form_data,
                                       today_stats={
                                           'total_reservations': total_reservations,
                                           'occupancy_rate': occupancy_rate
                                       })

            # Calculate cost
            total_cost, cost_breakdown = calculate_cost(start_time, end_time)

            # If reservation_id is provided, update existing reservation
            if 'reservation_id' in request.form and request.form['reservation_id']:
                conn.execute('''
                    UPDATE reservations 
                    SET date = ?, start_time = ?, end_time = ?, 
                        num_people = ?, contact_name = ?, 
                        contact_phone = ?, contact_email = ?, 
                        room_id = ?, total_cost = ?, cost_breakdown = ?
                    WHERE id = ?
                ''', (form_data['date'], form_data['start_time'],
                      form_data['end_time'], form_data['num_people'],
                      form_data['contact_name'], form_data['contact_phone'],
                      form_data['contact_email'], form_data['room_id'],
                      total_cost, str(cost_breakdown),
                      request.form['reservation_id']))
            else:
                # Create new reservation
                conn.execute('''
                    INSERT INTO reservations 
                    (date, start_time, end_time, num_people, 
                     contact_name, contact_phone, contact_email, room_id,
                     total_cost, cost_breakdown)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (form_data['date'], form_data['start_time'],
                      form_data['end_time'], form_data['num_people'],
                      form_data['contact_name'], form_data['contact_phone'],
                      form_data['contact_email'], form_data['room_id'],
                      total_cost, str(cost_breakdown)))

            conn.commit()
            return redirect(url_for('reservation'))

        except Exception as e:
            conn.rollback()
            flash(f'Error saving reservation: {str(e)}', 'error')
            return redirect(url_for('reservation'))

    # Get today's stats for the dashboard
    today = datetime.now().strftime('%Y-%m-%d')
    conn = get_db()

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

    return render_template('reservation.html',
                           rooms=get_rooms_with_reservations(),
                           today_stats={
                               'total_reservations': total_reservations,
                               'occupancy_rate': occupancy_rate
                           })


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
    conn.execute('DELETE FROM reservations WHERE id = ?', (reservation_id,))
    conn.commit()
    conn.close()
    return '', 204


@app.route('/update_reservation/<int:reservation_id>', methods=['POST'])
def update_reservation(reservation_id):
    data = request.get_json()
    conn = get_db()

    # Update the reservation time
    conn.execute('''
        UPDATE reservations 
        SET start_time = ? 
        WHERE id = ?
    ''', (data['start_time'], reservation_id))

    conn.commit()
    conn.close()
    return '', 204


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
