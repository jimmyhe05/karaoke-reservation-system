import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app
from services.db import get_db
from services.pricing import calculate_cost as calculate_cost_service
from services.auth import create_user, get_user_by_email

def seed_realistic_data():
    print("Starting realistic database seed...")
    conn = get_db()
    
    # 1. Ensure test users exist
    users_data = [
        {"email": "alice@gmail.com", "name": "Alice Johnson", "pwd": "password123"},
        {"email": "david.dev@company.com", "name": "David Miller", "pwd": "password123"},
        {"email": "sarah.sing@yahoo.com", "name": "Sarah Connor", "pwd": "password123"},
        {"email": "johndoe@example.com", "name": "John Doe", "pwd": "password123"},
        {"email": "lisa.anniversary@outlook.com", "name": "Lisa Wang", "pwd": "password123"},
    ]
    
    users = {}
    for ud in users_data:
        existing = get_user_by_email(ud["email"])
        if not existing:
            u = create_user(ud["email"], ud["pwd"], ud["name"])
            print(f"Created user: {ud['name']} ({ud['email']})")
            users[ud["email"]] = u
        else:
            users[ud["email"]] = existing
            
    # Clean up existing reservations to make a fresh demo look
    conn.execute("DELETE FROM reservation_history")
    conn.execute("DELETE FROM idle_reservations")
    conn.execute("DELETE FROM reservations")
    conn.commit()
    print("Cleared old reservations.")

    # 2. Setup dates
    chicago_tz = ZoneInfo("America/Chicago")
    today_dt = datetime.now(chicago_tz)
    
    yesterday = (today_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    today = today_dt.strftime("%Y-%m-%d")
    tomorrow = (today_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    friday = (today_dt + timedelta(days=(4 - today_dt.weekday()) % 7)).strftime("%Y-%m-%d") # Next Friday
    saturday = (today_dt + timedelta(days=(5 - today_dt.weekday()) % 7)).strftime("%Y-%m-%d") # Next Saturday
    
    # Tax rate
    tax_rate = app.config.get("TAX_RATE", 0.055)
    
    # Realistic reservations config
    reservations_to_seed = [
        # --- YESTERDAY (Historical, completed) ---
        {
            "user_email": "alice@gmail.com",
            "date": yesterday,
            "start_time": "14:00",
            "end_time": "16:00",
            "contact_name": "Alice Johnson",
            "contact_phone": "608-555-0143",
            "room_id": 1,
            "num_people": 5,
            "language": "en",
            "status": "completed",
            "notes": "Afternoon casual singing session with college friends. Need extra tea.",
        },
        {
            "user_email": "sarah.sing@yahoo.com",
            "date": yesterday,
            "start_time": "20:00",
            "end_time": "22:30",
            "contact_name": "Sarah Connor",
            "contact_phone": "608-555-0199",
            "room_id": 2,
            "num_people": 8,
            "language": "en",
            "status": "completed",
            "notes": "Sarah's birthday party! Bringing a cake, requested birthday decorations.",
        },
        
        # --- TODAY ---
        {
            "user_email": "david.dev@company.com",
            "date": today,
            "start_time": "18:00",
            "end_time": "20:00",
            "contact_name": "David Miller",
            "contact_phone": "312-555-4921",
            "room_id": 3,
            "num_people": 6,
            "language": "en",
            "status": "confirmed",
            "notes": "Corporate team building. Need HDMI hookup for a presentation screen if possible.",
        },
        {
            "user_email": "lisa.anniversary@outlook.com",
            "date": today,
            "start_time": "21:30",
            "end_time": "23:30",
            "contact_name": "Lisa Wang",
            "contact_phone": "608-555-9012",
            "room_id": 1,
            "num_people": 2,
            "language": "en",
            "status": "confirmed",
            "notes": "5th Anniversary celebration. Quiet table preferred. Requesting sweet red wine.",
        },
        {
            "user_email": "johndoe@example.com",
            "date": today,
            "start_time": "19:00",
            "end_time": "21:00",
            "contact_name": "John Doe",
            "contact_phone": "608-555-8888",
            "room_id": 2,
            "num_people": 4,
            "language": "zh",
            "status": "pending",
            "notes": "Wants to test out the Chinese pop song catalog. Bringing family.",
        },
        
        # --- TOMORROW ---
        {
            "user_email": "alice@gmail.com",
            "date": tomorrow,
            "start_time": "13:00",
            "end_time": "15:00",
            "contact_name": "Alice Johnson",
            "contact_phone": "608-555-0143",
            "room_id": 2,
            "num_people": 3,
            "language": "en",
            "status": "pending",
            "notes": "Study group taking a break. Will order food from the restaurant.",
        },
        {
            "user_email": "sarah.sing@yahoo.com",
            "date": tomorrow,
            "start_time": "17:00",
            "end_time": "19:30",
            "contact_name": "Sarah Connor",
            "contact_phone": "608-555-0199",
            "room_id": 3,
            "num_people": 7,
            "language": "en",
            "status": "confirmed",
            "notes": "Post-graduation dinner reservation followed by karaoke.",
        },
        
        # --- NEXT FRIDAY (High Volume) ---
        {
            "user_email": "david.dev@company.com",
            "date": friday,
            "start_time": "19:00",
            "end_time": "22:00",
            "contact_name": "David Miller",
            "contact_phone": "312-555-4921",
            "room_id": 1,
            "num_people": 8,
            "language": "en",
            "status": "pending",
            "notes": "Company social club Friday gathering.",
        },
        {
            "user_email": "johndoe@example.com",
            "date": friday,
            "start_time": "22:30",
            "end_time": "24:30",  # 10:30 PM - 12:30 AM
            "contact_name": "John Doe",
            "contact_phone": "608-555-8888",
            "room_id": 1,
            "num_people": 6,
            "language": "en",
            "status": "pending",
            "notes": "Late night weekend blowout. Happy hour drinks!",
        },
        {
            "user_email": "sarah.sing@yahoo.com",
            "date": friday,
            "start_time": "21:00",
            "end_time": "23:00",
            "contact_name": "Sarah Connor",
            "contact_phone": "608-555-0199",
            "room_id": 2,
            "num_people": 4,
            "language": "en",
            "status": "rejected",
            "notes": "Wanted outside hard liquor. Rejected due to venue alcohol license regulations.",
        },
        
        # --- NEXT SATURDAY ---
        {
            "user_email": "lisa.anniversary@outlook.com",
            "date": saturday,
            "start_time": "19:00",
            "end_time": "21:30",
            "contact_name": "Lisa Wang",
            "contact_phone": "608-555-9012",
            "room_id": 2,
            "num_people": 8,
            "language": "en",
            "status": "confirmed",
            "notes": "Family gathering celebration. Need a baby high chair.",
        },
        {
            "user_email": "alice@gmail.com",
            "date": saturday,
            "start_time": "20:00",
            "end_time": "22:00",
            "contact_name": "Alice Johnson",
            "contact_phone": "608-555-0143",
            "room_id": 3,
            "num_people": 5,
            "language": "en",
            "status": "cancelled",
            "notes": "Cancelled by customer - change of weekend plans.",
        }
    ]
    
    for r in reservations_to_seed:
        total_cost = calculate_cost_service(
            conn, r["room_id"], r["start_time"], r["end_time"], tax_rate
        )
        user_id = users[r["user_email"]]["id"]
        
        # Insert
        conn.execute(
            """INSERT INTO reservations
               (room_id, user_id, date, start_time, end_time, contact_name, contact_phone,
                contact_email, num_people, language, status, total_cost, notes, requested_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (
                r["room_id"],
                user_id,
                r["date"],
                r["start_time"],
                r["end_time"],
                r["contact_name"],
                r["contact_phone"],
                r["user_email"],
                r["num_people"],
                r["language"],
                r["status"],
                total_cost,
                r["notes"],
            ),
        )
    conn.commit()
    print(f"Successfully seeded {len(reservations_to_seed)} realistic reservations across multiple dates!")

if __name__ == "__main__":
    with app.app_context():
        seed_realistic_data()
