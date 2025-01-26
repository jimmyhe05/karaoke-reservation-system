# 🎤 Karaoke Reservation System

A practical tool designed to efficiently manage karaoke room reservations, inspired by the real-life operations at "Nam's Noodle" in Madison, WI. This application helps track bookings, calculate charges, and manage drink orders—all in one place. Built with Python and Flask, this system is perfect for small to medium-sized businesses offering karaoke services.

---

## 📋Table of Contents

- [Features](#features)
- [Demo](#demo)
- [Installation](#installation)
- [Technologies Used](#technologies-used)
- [Inspiration](#inspiration)

---

## ✨ Features

- **Reservation Management**: Add or delete reservations based on room availability.
- **Real-Time Availability**: Keep track of which rooms are booked at any given time.
- **Flexible Pricing**: Automatically calculate karaoke charges based on time slots:
  - Early Bird Special: $30/hour (12 PM - 6 PM)
  - Before 9 PM: $45/hour (6 PM - 9 PM)
  - After 9 PM: $50/hour (9 PM - 12 AM)
- **Tax Integration**: Includes a 5.5% sales tax for all calculations.
- **Drink Orders**: Add drink costs to the total bill with support for various beverages.
- **Dynamic Cost Calculation**: Handles overlapping time slots and tax-inclusive pricing.

---

## 🎥Demo

Here’s a glimpse of the Karaoke Reservation System in action:

![Demo GIF](demo.gif)  
<!-- *(If the GIF isn’t loading, check out the [live demo](#))* -->

---

## ⚙Installation

Follow these steps to run the project locally:

### Prerequisites
- Python 3.7+
- pip (Python package manager)

### Steps

1. **Clone the repository**:
   ```bash
   git clone https://github.com/jimmyhe05/karaoke-reservation-system.git
2. **Navigate to the project directory**:
   ```bash
   cd karaoke-reservation-system
4. **Run the application**:
   ```bash
   python app.py
6. **Access the app**:
   Open your browser and go to http://127.0.0.1:5000
   
