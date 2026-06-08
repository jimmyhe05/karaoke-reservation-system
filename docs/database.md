# Database Model

This app supports SQLite for local development and PostgreSQL for production.

Use SQLite locally:

```bash
DATABASE=karaoke.db
```

Use PostgreSQL in hosted environments:

```bash
DATABASE_URL=postgresql://user:password@host:5432/database?sslmode=require
```

## Tables

### rooms

Stores the bookable karaoke rooms and their pricing.

- `id`: primary key
- `name`: room display name
- `capacity`: maximum party size
- `hourly_rate`: standard rate
- `peak_hour_rate`: evening/late rate
- `created_at`: creation timestamp

### reservations

Stores customer bookings.

- `id`: primary key
- `room_id`: foreign key to `rooms.id`
- `date`: reservation date, `YYYY-MM-DD`
- `start_time`: reservation start, `HH:MM`
- `end_time`: reservation end, supports `24:00` to `25:00` for after midnight
- `contact_name`: customer name
- `contact_phone`: customer phone
- `contact_email`: optional customer email
- `num_people`: party size
- `language`: preferred language
- `status`: `confirmed`, `cancelled`, `completed`, or `no_show`
- `total_cost`: tax-inclusive reservation total
- `deposit_paid`: deposit amount
- `notes`: special requests
- `created_at`: creation timestamp
- `updated_at`: update timestamp

### idle_reservations

Tracks reservations temporarily removed from the room timeline.

- `id`: primary key
- `reservation_id`: foreign key to `reservations.id`
- `date`: date for timeline filtering
- `created_at`: creation timestamp

### audit_log

Stores admin/API actions for operational traceability.

- `id`: primary key
- `action`: action name
- `role`: acting role
- `path`: request path
- `method`: HTTP method
- `request_id`: request correlation ID
- `details`: JSON metadata
- `created_at`: creation timestamp

### reservation_history

Stores reservation snapshots after important changes.

- `id`: primary key
- `reservation_id`: foreign key to `reservations.id`
- `action`: action name
- `snapshot`: JSON reservation snapshot
- `created_at`: creation timestamp

## Future Extensions

Good next tables if the platform grows:

- `customers`: reusable customer profiles across repeat bookings
- `payments`: deposits, refunds, payment provider IDs, and status history
- `locations`: support multiple karaoke venues
- `room_maintenance_windows`: database-managed blackout windows
- `users`: real staff/admin accounts with password hashing and role management
