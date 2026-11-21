# VidyaSetu

VidyaSetu is a web-based school management platform that connects administrators, teachers, students, and parents. It simplifies attendance tracking, homework management, student records, and communication through secure, role-based dashboards, making school administration smarter and more efficient.

## Problem Statement

Many schools still rely on paper registers, scattered WhatsApp groups, and manual phone calls. Parents find out about absences late, homework gets missed, and administrators have no single view of the school. VidyaSetu brings all of this into one place.

## Features

- **Role-based login** for Admin/Dean, Teacher, HOD, Student, and Parent
- **Attendance tracking**: teachers mark attendance, and parents see the last 30 days
- **Homework management**: teachers assign work, students view it
- **Parent alerts**: parents are notified when their child is absent
- **Parent login with OTP** or with Admission ID and key
- **Student portal** with tiers for Classes 1-8, 9-10, and 11-12
- **Secure by design**: passwords are stored hashed, logins are signed, and only the school can register parents
- **Dashboards**: student and staff counts, attendance, and upcoming homework

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | HTML, CSS, JavaScript |
| Backend | Python (built-in HTTP server) |
| Database | SQLite |
| Auth | Hashed passwords, signed tokens, OTP |

## Project Structure

```
VidyaSetu/
├── index.html       # Login page (all portals)
├── dashboard.html   # Role-based dashboards
├── script.js        # Frontend logic
├── style.css        # Styling
├── server.py        # Backend API and database setup
├── package.json     # Project metadata
└── README.md
```

## Getting Started

### Requirements
- Python 3.8 or newer ([python.org](https://www.python.org/downloads/))

### Run locally
```bash
git clone https://github.com/travisaivarma2-eng/VidyaSetu.git
cd VidyaSetu
python server.py
```
Then open **http://localhost:3000** in your browser.

On the first run, the server creates `vidyasetu.db` and fills it with demo data. To reset the data, stop the server, delete `vidyasetu.db`, and run `python server.py` again.

## Demo Accounts

Demo accounts are loaded in the `seed()` function in `server.py`. Change them before any real use.

## Security Notes

- Passwords are hashed and never stored in plain text.
- The `.secret` file signs login tokens. Never commit or share it.
- Parent numbers can only be added by the school admin.
- OTPs are printed in the server terminal in demo mode. Connect an SMS provider for real use.

## Roadmap

- [ ] Admin forms to register students, teachers, and parents
- [ ] Real SMS delivery for OTP
- [ ] Fee management and receipts
- [ ] Timetable and exam results
- [ ] Mobile app
- [ ] Multi-language support (Telugu, Hindi, English)

## Team

Built for a hackathon by **N. Shivanand Reddy**, **T. Ravi Sai Varma**, and **Md. Rehan**.
Update this section with your real team names and roles.

## License

MIT License
