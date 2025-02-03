from flask import Flask, render_template, request, redirect, url_for
from datetime import datetime, timedelta

app = Flask(__name__)

reservations = []

TAX_RATE = 0.055


def calculate_cost(start_time, end_time):
    """Calculate total karaoke charge based on the time spent in the room."""
    total_cost = 0
    cost_breakdown = []

    current_time = start_time
    while current_time < end_time:
        if 11 <= current_time.hour < 18:
            rate = 30  # Early Bird Special
            segment = "Early Bird Special"
        elif 18 <= current_time.hour < 21:
            rate = 45  # Before 9 PM
            segment = "Before 9 PM"
        elif 21 <= current_time.hour < 24:
            rate = 50  # After 9 PM
            segment = "After 9 PM"
        else:
            rate = 50  # Default rate after midnight
            segment = "After 9 PM"

        next_hour = current_time.replace(
            minute=0, second=0, microsecond=0) + timedelta(hours=1)

        if next_hour > end_time:
            minutes = (end_time - current_time).seconds / \
                60
            total_cost += rate * (minutes / 60)
            cost_breakdown.append(
                f"{segment}: {minutes} minutes at ${rate} per hour = ${round(rate * (minutes / 60), 2)}")
            break
        else:
            total_cost += rate
            cost_breakdown.append(
                f"{segment}: 60 minutes at ${rate} per hour = ${rate}")

        current_time = next_hour

    total_cost_with_tax = total_cost * (1 + TAX_RATE)
    return round(total_cost_with_tax, 2), cost_breakdown


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
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

        start_time = datetime.fromisoformat(reservation['start_time'])
        end_time = datetime.fromisoformat(reservation['end_time'])

        reservation['formatted_start_time'] = start_time.strftime(
            '%Y-%m-%d %I:%M %p')
        reservation['formatted_end_time'] = end_time.strftime(
            '%Y-%m-%d %I:%M %p')
        reservation['total_cost'], reservation['cost_breakdown'] = calculate_cost(
            start_time, end_time)

        reservations.append(reservation)
        return redirect(url_for('index'))

    room_1_reservations = [r for r in reservations if r['room_id'] == 'R1']
    room_2_reservations = [r for r in reservations if r['room_id'] == 'R2']
    room_3_reservations = [r for r in reservations if r['room_id'] == 'R3']

    return render_template('index.html', room_1_reservations=room_1_reservations,
                           room_2_reservations=room_2_reservations, room_3_reservations=room_3_reservations)


@app.route('/remove/<int:index>', methods=['POST'])
def remove_reservation(index):
    if 0 <= index < len(reservations):
        reservations.pop(index)
    return redirect(url_for('index'))


@app.route('/edit/<int:index>', methods=['GET', 'POST'])
def edit_reservation(index):
    if 0 <= index < len(reservations):
        reservation = reservations[index]

        if request.method == 'POST':
            reservation['customer_name'] = request.form['customer_name']
            reservation['customer_email'] = request.form['customer_email']
            reservation['customer_phone'] = request.form['customer_phone']
            reservation['num_people'] = request.form['num_people']
            reservation['language'] = request.form['language']
            reservation['room_id'] = request.form['room_id']

            reservation['start_time'] = request.form['new_start_time']
            reservation['end_time'] = request.form['new_end_time']

            start_time = datetime.fromisoformat(reservation['start_time'])
            end_time = datetime.fromisoformat(reservation['end_time'])

            reservation['formatted_start_time'] = start_time.strftime(
                '%Y-%m-%d %I:%M %p')
            reservation['formatted_end_time'] = end_time.strftime(
                '%Y-%m-%d %I:%M %p')

            reservation['total_cost'], reservation['cost_breakdown'] = calculate_cost(
                start_time, end_time)

            return redirect(url_for('index'))

        return render_template('edit_reservation.html', reservation=reservation, index=index)

    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True)
