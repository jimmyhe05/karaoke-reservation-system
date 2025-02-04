from flask import Flask, render_template, request, redirect, url_for, flash
from datetime import datetime, timedelta
import os

app = Flask(__name__)
app.secret_key = os.urandom(24)

reservations = []
TAX_RATE = 0.055

# Business hours: 11 AM to 1 AM
OPEN_HOUR = 11
CLOSE_HOUR = 1


def is_within_business_hours(start_time, end_time):
    """Check if the reservation falls within business hours (11 AM - 1 AM)."""
    # Convert 1 AM to 25 for easier comparison
    start_hour = start_time.hour if start_time.hour >= OPEN_HOUR else start_time.hour + 24
    end_hour = end_time.hour if end_time.hour >= OPEN_HOUR else end_time.hour + 24

    # Business hours are from 11 AM (11) to 1 AM (25)
    return OPEN_HOUR <= start_hour < 25 and OPEN_HOUR <= end_hour < 25


def is_room_available(room_id, start_time, end_time, exclude_index=None):
    """Check if the room is available for the given time slot."""
    for i, reservation in enumerate(reservations):
        if i == exclude_index:
            continue  # Skip the reservation being edited
        if reservation['room_id'] == room_id:
            existing_start = datetime.fromisoformat(reservation['start_time'])
            existing_end = datetime.fromisoformat(reservation['end_time'])
            if (start_time < existing_end) and (end_time > existing_start):
                return False
    return True


def calculate_cost(start_time, end_time):
    """Calculate total karaoke charge based on the time spent in the room."""
    total_cost = 0
    cost_breakdown = []

    # Handle overnight reservations
    if end_time <= start_time:
        end_time += timedelta(days=1)

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
                "The restaurant is closed between 1 AM and 11 AM.")

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


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # print(request.form)

        reservation = {
            'customer_name': request.form['customer_name'],
            'customer_email': request.form['customer_email'],
            'customer_phone': request.form['customer_phone'],
            'num_people': request.form['num_people'],
            'language': request.form['language'],
            'room_id': request.form['room_id'],
            'start_time': request.form['start_time'],
            'end_time': request.form['end_time'],
            'total_cost': 0,
            'cost_breakdown': []
        }

        try:
            start_time = datetime.fromisoformat(reservation['start_time'])
            end_time = datetime.fromisoformat(reservation['end_time'])

            # print("Start Time:", start_time)  # Debugging
            # print("End Time:", end_time)  # Debugging

            # Validate business hours
            if not is_within_business_hours(start_time, end_time):
                print("Business hours check failed!")
                flash("Reservations are only allowed between 11 AM and 1 AM.", "error")
                return redirect(url_for('index'))

            # Validate room availability
            if not is_room_available(reservation['room_id'], start_time, end_time):
                print("Room is not available!")
                flash("The selected room is already booked for this time slot.", "error")
                return redirect(url_for('index'))

            reservation['formatted_start_time'] = start_time.strftime(
                '%Y-%m-%d %I:%M %p')
            reservation['formatted_end_time'] = end_time.strftime(
                '%Y-%m-%d %I:%M %p')
            reservation['total_cost'], reservation['cost_breakdown'] = calculate_cost(
                start_time, end_time)

            # Debugging before adding
            print("Reservation to be added:", reservation)
            reservations.append(reservation)  # ADD TO LIST HERE
            # Debugging after adding
            print("Updated reservations list:", reservations)

            flash("Reservation successfully created!", "success")

        except ValueError as e:
            flash(f"Invalid input: {str(e)}", "error")

        return redirect(url_for('index'))

    room_1_reservations = [r for r in reservations if r['room_id'] == 'R1']
    room_2_reservations = [r for r in reservations if r['room_id'] == 'R2']
    room_3_reservations = [r for r in reservations if r['room_id'] == 'R3']

    return render_template('index.html',
                           room_1_reservations=room_1_reservations,
                           room_2_reservations=room_2_reservations,
                           room_3_reservations=room_3_reservations)


@app.route('/remove/<int:index>', methods=['POST'])
def remove_reservation(index):
    if 0 <= index < len(reservations):
        reservations.pop(index)
        flash("Reservation successfully canceled!", "success")
    else:
        flash("Invalid reservation index.", "error")
    return redirect(url_for('index'))


@app.route('/edit/<int:index>', methods=['GET', 'POST'])
def edit_reservation(index):
    if 0 <= index < len(reservations):
        reservation = reservations[index]

        if request.method == 'POST':
            try:
                # Get new reservation details
                new_customer_name = request.form['customer_name']
                new_customer_email = request.form['customer_email']
                new_customer_phone = request.form['customer_phone']
                new_num_people = request.form['num_people']
                new_language = request.form['language']
                new_room_id = request.form['room_id']
                new_start_time = datetime.fromisoformat(
                    request.form['new_start_time'])
                new_end_time = datetime.fromisoformat(
                    request.form['new_end_time'])

                # Validate business hours
                if not is_within_business_hours(new_start_time, new_end_time):
                    flash(
                        "Reservations are only allowed between 11 AM and 1 AM.", "error")
                    return render_template('edit_reservation.html', reservation=reservation, index=index)

                # Check room availability (excluding the current reservation)
                if not is_room_available(new_room_id, new_start_time, new_end_time, exclude_index=index):
                    flash(
                        "The selected room is already booked for this time slot.", "error")
                    return render_template('edit_reservation.html', reservation=reservation, index=index)

                # Update reservation
                reservation['customer_name'] = new_customer_name
                reservation['customer_email'] = new_customer_email
                reservation['customer_phone'] = new_customer_phone
                reservation['num_people'] = new_num_people
                reservation['language'] = new_language
                reservation['room_id'] = new_room_id
                reservation['start_time'] = request.form['new_start_time']
                reservation['end_time'] = request.form['new_end_time']
                reservation['formatted_start_time'] = new_start_time.strftime(
                    '%Y-%m-%d %I:%M %p')
                reservation['formatted_end_time'] = new_end_time.strftime(
                    '%Y-%m-%d %I:%M %p')
                reservation['total_cost'], reservation['cost_breakdown'] = calculate_cost(
                    new_start_time, new_end_time)

                flash("Reservation successfully updated!", "success")
                return redirect(url_for('index'))

            except ValueError as e:
                flash(f"Invalid input: {str(e)}", "error")
                return render_template('edit_reservation.html', reservation=reservation, index=index)

        return render_template('edit_reservation.html', reservation=reservation, index=index)

    flash("Invalid reservation index.", "error")
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True)
