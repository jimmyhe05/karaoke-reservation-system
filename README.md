# 🎤 Karaoke Reservation System

A **powerful and user-friendly web application** designed to manage karaoke room reservations efficiently. Inspired by the real-life operations at **Nam's Noodle** in Madison, WI, this system enables **real-time room booking**, **dynamic pricing**, and **automated cost calculations**.

Built with **Python (Flask)** for the backend, **HTML/CSS/JavaScript** for the frontend, and **Bootstrap** for styling, this tool is ideal for small to medium-sized karaoke businesses looking to streamline their operations.

---

## 📋 Table of Contents

1. [✨ Features](#-features)
2. [🎥 Demo](#-demo)
3. [⚙ Installation](#-installation)
4. [🖥 Technologies Used](#-technologies-used)
5. [💡 Inspiration](#-inspiration)
6. [🌟 Future Enhancements](#-future-enhancements)
7. [🔗 Connect with Me](#-connect-with-me)

---

## ✨ Features

- **Reservation Management** – Easily add, edit, or remove reservations for available rooms.
- **Real-Time Availability** – Instantly see which rooms are booked and available.
- **Dynamic Pricing System** – Automatically calculates cost based on time slots:
  - 🕛 **Early Bird Special**: $30/hour (11 AM - 6 PM)
  - 🌆 **Prime Time**: $45/hour (6 PM - 9 PM)
  - 🌙 **Late Night**: $50/hour (9 PM - 1 AM)
- **Business Hours Enforcement** – Ensures bookings fall within 11 AM - 1 AM.
- **Tax Calculation** – 5.5% tax is automatically applied to all reservations.
- **Intuitive UI** – Simple and modern CSS styling, interactive modals, and error messages for an enhanced user experience.
- **Validation & Conflict Handling** – Prevents double bookings and ensures valid time selections.

---

## 🎥 Demo

Here’s a preview of how the system works:
![Demo GIF](karaoke-reservation-system.gif)  

---

## ⚙ Installation

### Requirements

- Python 3.x
- pip

### Setup Steps

1. **Clone the repository**:
   ```bash
   git clone https://github.com/jimmyhe05/karaoke-reservation-system.git

2. **Navigate to the project folder**:
   ```bash
   cd karaoke-reservation-system

3. **Create a virtual environment (optional but recommended)**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use: venv\Scripts\activate

4. **Install dependencies**:
   ```bash
   pip install flask

5. **Run the Flask application**:
   ```bash
   python app.py

6. **Access the app in your browser**:
   Open http://127.0.0.1:5000.

---

## 🖥 Technologies Used

| Technology   | Description                          |
|--------------|--------------------------------------|
| **Python** 🐍 | Backend logic & calculations         |
| **Flask** 🔥  | Lightweight web framework            |
| **HTML5** 🎨 | Page structure                       |
| **CSS3** 🎭  | Styling & responsiveness             |
| **JavaScript** ✨ | Interactive UI & modal popups     |
| **Bootstrap** 🎨 | Enhanced UI components             |

---

## 💡 Inspiration

This project was inspired by my experience working at **Nam's Noodle**, a family-owned restaurant in **Madison, Wisconsin**. The restaurant features karaoke rooms, and managing reservations manually became a frustrating and time-consuming process.

With this automated system, I aimed to:

- ✅ **Eliminate double bookings**
- ✅ **Streamline reservation management**
- ✅ **Ensure customers are charged correctly**
- ✅ **Improve the overall efficiency of running karaoke services**

Now, managing room availability, pricing, and customer details is fast, simple, and efficient! 🚀

---

## 🌟 Future Enhancements

- **User Authentication** – Secure login for staff & admins.
- **Payment Integration** – Add online payment support.
- **Multi-language Support** – Localized UI for diverse users.

---

## 🔗 Connect with Me

- **GitHub**: [jimmyhe05](https://github.com/jimmyhe05)
- **Email**: jimmyhe05@gmail.com
- **LinkedIn**: [jimmy-he-badger](https://www.linkedin.com/in/jimmy-he-badger/)

Feel free to contribute, report issues, or suggest features! Enjoy your karaoke nights hassle-free! 🎶🎤

---