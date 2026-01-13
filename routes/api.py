from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, session

from services.db import get_db
from services.http import api_error, api_ok, require_admin
from services.validation import parse_time_safe, normalize_time_range, find_conflict
from flask import current_app
from services.pricing import compute_pricing
from services.reservations import (
    fetch_idle_set,
    serialize_reservation_row,
    create_reservation_api_payload,
    update_reservation_api_payload,
    delete_reservation_api_payload,
)

api_bp = Blueprint('api', __name__)


@api_bp.route('/api/daily_reservations')
@require_admin
def api_daily_reservations():
    date = request.args.get('date', None)
    if not date:
        return api_error('Date parameter is required', 400, code='validation_error', fields=['date'])

    conn = get_db()
    try:
        rooms = conn.execute('SELECT * FROM rooms WHERE id > 0 ORDER BY id').fetchall()
        reservations = conn.execute(
            '''SELECT * FROM reservations WHERE date = ? ORDER BY room_id, start_time''', (date,)
        ).fetchall()
        idle_set = fetch_idle_set(conn, date)

        result = {'date': date, 'rooms': []}
        for room in rooms:
            room_res = []
            for res in reservations:
                if res['room_id'] != room['id']:
                    continue
                room_res.append(serialize_reservation_row(res, res['id'] in idle_set))
            result['rooms'].append({
                'room_id': room['id'],
                'room_name': room['name'],
                'reservations': room_res,
            })
        return api_ok(result)
    finally:
        conn.close()


@api_bp.route('/api/reservations', methods=['GET'])
@require_admin
def api_list_reservations():
    date = request.args.get('date')
    room_id = request.args.get('room_id')
    status = request.args.get('status')

    room_filter = None
    if room_id is not None:
        try:
            room_filter = int(room_id)
        except Exception:
            return api_error('Invalid room id', 400, code='validation_error', fields=['room_id'])

    conn = get_db()
    params = []
    query = 'SELECT * FROM reservations WHERE 1=1'
    if date:
        query += ' AND date = ?'
        params.append(date)
    if room_filter is not None:
        query += ' AND room_id = ?'
        params.append(room_filter)
    if status:
        query += ' AND status = ?'
        params.append(status)
    query += ' ORDER BY date, room_id, start_time'

    rows = conn.execute(query, params).fetchall()
    idle_set = fetch_idle_set(conn, date if date else None)
    reservations = [serialize_reservation_row(r, r['id'] in idle_set) for r in rows]
    return api_ok({'reservations': reservations})


@api_bp.route('/api/reservations/<int:reservation_id>', methods=['GET'])
@require_admin
def api_get_reservation(reservation_id):
    conn = get_db()
    row = conn.execute('SELECT * FROM reservations WHERE id = ?', (reservation_id,)).fetchone()
    if not row:
        return api_error('Reservation not found', 404, code='not_found')
    idle_set = fetch_idle_set(conn)
    return api_ok({'reservation': serialize_reservation_row(row, row['id'] in idle_set)})


@api_bp.route('/api/reservations', methods=['POST'])
@require_admin
def api_create_reservation():
    return create_reservation_api_payload(request.get_json() or {}, api_error, api_ok)


@api_bp.route('/api/reservations/<int:reservation_id>', methods=['PATCH'])
@require_admin
def api_update_reservation_route(reservation_id):
    return update_reservation_api_payload(reservation_id, request.get_json() or {}, api_error, api_ok)


@api_bp.route('/api/reservations/<int:reservation_id>', methods=['DELETE'])
@require_admin
def api_delete_reservation_route(reservation_id):
    return delete_reservation_api_payload(reservation_id, api_error, api_ok)


@api_bp.route('/api/public_schedule')
def public_schedule():
    date = request.args.get('date')
    if not date:
        return jsonify({'error': 'Date parameter is required'}), 400

    conn = get_db()
    rooms = conn.execute('SELECT * FROM rooms WHERE id > 0 ORDER BY id').fetchall()
    reservations = conn.execute('SELECT * FROM reservations WHERE date = ? ORDER BY start_time', (date,)).fetchall()
    idle_set = fetch_idle_set(conn, date)

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


@api_bp.route('/api/room_availability')
def check_room_availability():
    date = request.args.get('date')
    if not date:
        return jsonify({'error': 'Date parameter is required'}), 400

    try:
        datetime_obj = datetime.strptime(date, '%Y-%m-%d').date()  # noqa: F841
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400

    conn = get_db()
    try:
        rooms = conn.execute('SELECT id FROM rooms WHERE id > 0').fetchall()
        room_ids = [room['id'] for room in rooms]

        booked_rooms = conn.execute('''
            SELECT DISTINCT room_id
            FROM reservations
            WHERE date = ?
        ''', (date,)).fetchall()
        booked_room_ids = [room['room_id'] for room in booked_rooms]

        available_rooms = list(set(room_ids) - set(booked_room_ids))

        return jsonify({
            'available_rooms': available_rooms,
            'total_rooms': len(room_ids),
            'booked_rooms': len(booked_room_ids)
        })
    finally:
        conn.close()


@api_bp.route('/api/calendar_availability')
def api_calendar_availability():
    date = request.args.get('date')
    if not date:
        return api_error('Date parameter is required', 400, code='validation_error', fields=['date'])

    conn = get_db()
    rooms = conn.execute(
        'SELECT id, name FROM rooms WHERE id > 0 ORDER BY id'
    ).fetchall()
    reservations = conn.execute(
        'SELECT * FROM reservations WHERE date = ? ORDER BY room_id, start_time',
        (date,)
    ).fetchall()

    by_room = {r['id']: {'name': r['name'], 'reservations': []} for r in rooms}
    idle_set = fetch_idle_set(conn, date)

    for res in reservations:
        if res['id'] in idle_set:
            continue
        by_room[res['room_id']]['reservations'].append({
            'start_time': res['start_time'],
            'end_time': res['end_time'],
            'status': res['status'],
        })

    return api_ok({'date': date, 'rooms': by_room})


@api_bp.route('/api/price_estimate', methods=['POST'])
@require_admin
def price_estimate():
    payload = request.get_json() or {}
    room_id = payload.get('room_id')
    start_time = payload.get('start_time')
    end_time = payload.get('end_time')

    if room_id is None or not start_time or not end_time:
        return api_error(
            'Missing required fields',
            400,
            code='validation_error',
            fields=['room_id', 'start_time', 'end_time'],
        )

    try:
        room_id_int = int(room_id)
    except Exception:
        return api_error('Invalid room id', 400, code='validation_error', fields=['room_id'])

    try:
        normalized_start, normalized_end, _, _ = normalize_time_range(payload.get('date', ''), start_time, end_time)
    except ValueError as e:
        return api_error(str(e), 400, code='validation_error', fields=['start_time', 'end_time'])

    pricing = compute_pricing(
        get_db(),
        room_id_int,
        normalized_start,
        normalized_end,
        current_app.config['TAX_RATE'],
    )
    return api_ok({'pricing': pricing})


@api_bp.route('/api/room_suggestion', methods=['POST'])
@require_admin
def room_suggestion():
    data = request.get_json() or {}
    date = data.get('date')
    start_time = data.get('start_time')
    end_time = data.get('end_time')
    try:
        num_people = int(data.get('num_people', 0))
    except Exception:
        return api_error('Invalid number of people', 400, code='validation_error', fields=['num_people'])

    if not date or not start_time or not end_time:
        return api_error('Missing required fields', 400, code='validation_error')

    conn = get_db()
    rooms = conn.execute('SELECT id, capacity FROM rooms WHERE id > 0').fetchall()

    candidates = []
    for room in rooms:
        if room['capacity'] < num_people:
            continue
        conflict = find_conflict(conn, room['id'], date, start_time, end_time)
        if conflict:
            continue
        candidates.append(room['id'])

    return api_ok({'room_ids': candidates})


@api_bp.route('/api/alternative_times', methods=['POST'])
@require_admin
def alternative_times():
    data = request.get_json() or {}
    date = data.get('date')
    start_time = data.get('start_time')
    end_time = data.get('end_time')
    room_id = data.get('room_id')

    if not date or not start_time or not end_time or not room_id:
        return api_error('Missing required fields', 400, code='validation_error')

    conn = get_db()
    try:
        room_id_int = int(room_id)
    except Exception:
        return api_error('Invalid room id', 400, code='validation_error', fields=['room_id'])

    # Try small shifts in 30-min increments up to +/- 2 hours
    shifts = [-120, -90, -60, -30, 30, 60, 90, 120]
    alternatives = []
    try:
        start_dt, _ = parse_time_safe(start_time)
        end_dt, _ = parse_time_safe(end_time)
    except ValueError as e:
        return api_error(str(e), 400, code='validation_error', fields=['start_time', 'end_time'])

    for minutes in shifts:
        shifted_start = (start_dt + timedelta(minutes=minutes)).strftime('%H:%M')
        shifted_end = (end_dt + timedelta(minutes=minutes)).strftime('%H:%M')
        if shifted_end <= shifted_start:
            continue
        conflict = find_conflict(conn, room_id_int, date, shifted_start, shifted_end)
        if not conflict:
            alternatives.append({'start_time': shifted_start, 'end_time': shifted_end})

    return api_ok({'alternatives': alternatives})


@api_bp.route('/api/me')
def api_me():
    role = session.get('role', 'guest')
    return api_ok({'is_admin': role == 'admin', 'role': role})
