# Cloud-Based Team Task Tracker & PMT

Internship-level Project Management / Team Task Tracker built with Python, Flask and MongoDB.

## Included features
- Registration, login, logout and password hashing
- Four roles: Admin, Project Manager, Team Lead, Employee
- Role-aware dashboard
- User management
- Project CRUD
- Team member assignment
- Task CRUD
- Task assignment/reassignment
- Priority, status, deadline and progress tracking
- Comments
- Notifications
- Overdue task detection
- Search and filters
- Activity logs
- Dashboard statistics and simple charts
- Reports and CSV export
- Responsive PMT-style UI
- MongoDB collections for users, projects, tasks, comments, notifications and activity logs
- JSON API endpoints for dashboard/tasks
- Local MongoDB and MongoDB Atlas compatible

## Run
1. Install Python 3.10+.
2. Start MongoDB locally, OR use MongoDB Atlas.
3. Copy `.env.example` to `.env` and update MONGO_URI if needed.
4. Open CMD in this folder.
5. `python -m pip install -r requirements.txt`
6. `python app.py`
7. Open http://127.0.0.1:5000

## Demo accounts
The app provides a `/seed` route for development. Open:
http://127.0.0.1:5000/seed

It creates:
admin@tracker.com / Admin@123
pm@tracker.com / PM@12345
tl@tracker.com / TL@12345
employee@tracker.com / Employee@123

For real deployment, change these credentials and remove/disable the seed route.

## Cloud concept
The application is designed so Flask can be hosted on a cloud platform and MongoDB can be hosted using MongoDB Atlas. Set MONGO_URI to the Atlas connection string for cloud deployment.
