import os, csv, io
from functools import wraps
from datetime import datetime, date
from bson import ObjectId
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, make_response
from pymongo import MongoClient, ASCENDING, DESCENDING
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__, template_folder=".")
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = "cloud_team_task_tracker"

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
db = client[DB_NAME]
users = db.users
projects = db.projects
tasks = db.tasks
comments = db.comments
notifications = db.notifications
logs = db.activity_logs

try:
    client.admin.command("ping")
    print("MongoDB Connected Successfully!")
except Exception as e:
    print("MongoDB connection error:", e)

for c, idx in [(users,"email"), (projects,"name"), (tasks,"title")]:
    try: c.create_index([(idx, ASCENDING)])
    except: pass

def oid(x):
    try: return ObjectId(x)
    except: return None

def current_user():
    x = session.get("user_id")
    return users.find_one({"_id": oid(x)}) if x else None

def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not current_user():
            flash("Please login first.", "warning")
            return redirect(url_for("login"))
        return f(*a, **kw)
    return wrapper

def roles(*allowed):
    def deco(f):
        @wraps(f)
        def wrapper(*a, **kw):
            u=current_user()
            if not u:
                return redirect(url_for("login"))
            if u.get("role") not in allowed:
                flash("You do not have permission for this action.", "danger")
                return redirect(url_for("dashboard"))
            return f(*a, **kw)
        return wrapper
    return deco

def log(action, detail=""):
    u=current_user()
    logs.insert_one({"user_id": str(u["_id"]) if u else None,
                     "user_name": u["name"] if u else "System",
                     "action": action, "detail": detail,
                     "created_at": datetime.now()})

def notify(user_id, message, kind="info"):
    if user_id:
        notifications.insert_one({"user_id": str(user_id), "message":message,
                                  "kind":kind, "read":False, "created_at":datetime.now()})

def names_for_ids(ids):
    vals=[]
    for x in ids or []:
        u=users.find_one({"_id": oid(x)})
        if u: vals.append({"id":str(u["_id"]), "name":u["name"], "role":u["role"]})
    return vals

@app.context_processor
def globals():
    u=current_user()
    unread=notifications.count_documents({"user_id":str(u["_id"]),"read":False}) if u else 0
    return {"me":u, "unread_notifications":unread}

@app.route("/")
def home():
    return redirect(url_for("dashboard") if current_user() else url_for("login"))

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method=="POST":
        name=request.form.get("name","").strip()
        email=request.form.get("email","").strip().lower()
        password=request.form.get("password","")
        role=request.form.get("role","Employee")
        if not name or not email or not password:
            flash("All fields are required.","danger"); return redirect(url_for("register"))
        if users.find_one({"email":email}):
            flash("Email already exists.","warning"); return redirect(url_for("register"))
        # Public registration intentionally restricts privileged roles.
        if role not in ["Employee","Team Lead"]:
            role="Employee"
        users.insert_one({"name":name,"email":email,
            "password":generate_password_hash(password),"role":role,
            "status":"Active","created_at":datetime.now()})
        flash("Account created. Login now.","success")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        email=request.form.get("email","").strip().lower()
        password=request.form.get("password","")
        u=users.find_one({"email":email})
        if u and u.get("status","Active")=="Active" and check_password_hash(u["password"],password):
            session.clear(); session["user_id"]=str(u["_id"])
            log("Login","Successful login")
            return redirect(url_for("dashboard"))
        flash("Invalid credentials or inactive account.","danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    if current_user(): log("Logout","User logged out")
    session.clear(); return redirect(url_for("login"))

@app.route("/seed")
def seed():
    if users.count_documents({})==0:
        demo=[
            ("System Admin","admin@tracker.com","Admin","Admin@123"),
            ("Project Manager","pm@tracker.com","Project Manager","PM@12345"),
            ("Team Lead","tl@tracker.com","Team Lead","TL@12345"),
            ("Employee One","employee@tracker.com","Employee","Employee@123")]
        for n,e,r,p in demo:
            users.insert_one({"name":n,"email":e,"role":r,"status":"Active",
                              "password":generate_password_hash(p),"created_at":datetime.now()})
        flash("Demo users created. See README for credentials.","success")
    else: flash("Users already exist.","info")
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    u=current_user(); role=u["role"]; uid=str(u["_id"])
    q={}
    if role=="Employee": q={"$or":[{"assigned_to":uid},{"created_by":uid}]}
    elif role=="Team Lead": q={"team_lead":uid}
    pquery={}
    if role=="Employee": pquery={"member_ids":uid}
    elif role=="Team Lead": pquery={"team_lead":uid}
    stat_tasks=list(tasks.find(q))
    stat_projects=projects.count_documents(pquery)
    if role in ("Admin","Project Manager"):
        stat_projects=projects.count_documents({})
        stat_tasks=list(tasks.find({}))
    total=len(stat_tasks); completed=sum(1 for x in stat_tasks if x.get("status")=="Completed")
    overdue=sum(1 for x in stat_tasks if x.get("due_date") and x.get("due_date") < date.today().isoformat() and x.get("status")!="Completed")
    status_counts={s:sum(1 for x in stat_tasks if x.get("status")==s) for s in ["To Do","In Progress","Review","Completed"]}
    priority_counts={p:sum(1 for x in stat_tasks if x.get("priority")==p) for p in ["Low","Medium","High","Critical"]}
    return render_template("dashboard.html", total_tasks=total, completed=completed,
        overdue=overdue,total_projects=stat_projects,status_counts=status_counts,
        priority_counts=priority_counts)

@app.route("/users")
@roles("Admin")
def user_list():
    return render_template("users.html", users=list(users.find().sort("created_at",DESCENDING)))

@app.route("/users/<id>/toggle", methods=["POST"])
@roles("Admin")
def user_toggle(id):
    u=users.find_one({"_id":oid(id)})
    if u: users.update_one({"_id":u["_id"]},{"$set":{"status":"Inactive" if u.get("status")=="Active" else "Active"}})
    log("User status changed", id); return redirect(url_for("user_list"))

@app.route("/projects")
@login_required
def project_list():
    u=current_user(); role=u["role"]; q={}
    if role=="Employee": q={"member_ids":str(u["_id"])}
    elif role=="Team Lead": q={"team_lead":str(u["_id"])}
    ps=list(projects.find(q).sort("created_at",DESCENDING))
    return render_template("projects.html", projects=ps, members=list(users.find({"status":"Active"})))

@app.route("/projects/new", methods=["GET","POST"])
@roles("Admin","Project Manager")
def project_new():
    if request.method=="POST":
        member_ids=request.form.getlist("member_ids")
        p={"name":request.form["name"].strip(),"description":request.form.get("description",""),
           "status":request.form.get("status","Planning"),
           "priority":request.form.get("priority","Medium"),
           "start_date":request.form.get("start_date",""),
           "due_date":request.form.get("due_date",""),
           "team_lead":request.form.get("team_lead",""),
           "member_ids":member_ids,"created_by":str(current_user()["_id"]),
           "created_at":datetime.now()}
        r=projects.insert_one(p)
        for mid in member_ids: notify(mid,f"You were added to project: {p['name']}","project")
        if p["team_lead"]: notify(p["team_lead"],f"You are Team Lead for: {p['name']}","project")
        log("Project created",p["name"])
        return redirect(url_for("project_list"))
    return render_template("project_form.html", project=None, members=list(users.find({"status":"Active"})))

@app.route("/projects/<id>/edit", methods=["GET","POST"])
@roles("Admin","Project Manager")
def project_edit(id):
    p=projects.find_one({"_id":oid(id)})
    if not p: flash("Project not found","danger"); return redirect(url_for("project_list"))
    if request.method=="POST":
        data={"name":request.form["name"].strip(),"description":request.form.get("description",""),
              "status":request.form.get("status","Planning"),"priority":request.form.get("priority","Medium"),
              "start_date":request.form.get("start_date",""),"due_date":request.form.get("due_date",""),
              "team_lead":request.form.get("team_lead",""),"member_ids":request.form.getlist("member_ids")}
        projects.update_one({"_id":p["_id"]},{"$set":data}); log("Project updated",data["name"])
        return redirect(url_for("project_list"))
    return render_template("project_form.html",project=p,members=list(users.find({"status":"Active"})))

@app.route("/projects/<id>/delete", methods=["POST"])
@roles("Admin","Project Manager")
def project_delete(id):
    p=projects.find_one({"_id":oid(id)})
    if p:
        projects.delete_one({"_id":p["_id"]}); tasks.delete_many({"project_id":str(p["_id"])})
        log("Project deleted",p["name"])
    return redirect(url_for("project_list"))

@app.route("/tasks")
@login_required
def task_list():
    u=current_user(); role=u["role"]; q={}
    if role=="Employee": q={"assigned_to":str(u["_id"])}
    elif role=="Team Lead": q={"$or":[{"assigned_to":str(u["_id"])},{"team_lead":str(u["_id"])}]}
    search=request.args.get("q","").strip()
    status=request.args.get("status","")
    priority=request.args.get("priority","")
    if search: q["title"]={"$regex":search,"$options":"i"}
    if status: q["status"]=status
    if priority: q["priority"]=priority
    ts=list(tasks.find(q).sort("created_at",DESCENDING))
    for t in ts:
        t["project_name"]=projects.find_one({"_id":oid(t.get("project_id"))},{"name":1}).get("name","") if t.get("project_id") else ""
        t["assignee"]=users.find_one({"_id":oid(t.get("assigned_to"))},{"name":1}).get("name","Unassigned") if t.get("assigned_to") else "Unassigned"
    return render_template("tasks.html",tasks=ts, projects=list(projects.find()),
                           members=list(users.find({"status":"Active"})),filters={"q":search,"status":status,"priority":priority})

@app.route("/tasks/new", methods=["GET","POST"])
@roles("Admin","Project Manager","Team Lead")
def task_new():
    if request.method=="POST":
        data={"title":request.form["title"].strip(),"description":request.form.get("description",""),
              "project_id":request.form.get("project_id",""),"assigned_to":request.form.get("assigned_to",""),
              "priority":request.form.get("priority","Medium"),"status":request.form.get("status","To Do"),
              "progress":int(request.form.get("progress",0) or 0),"start_date":request.form.get("start_date",""),
              "due_date":request.form.get("due_date",""),"created_by":str(current_user()["_id"]),
              "created_at":datetime.now(),"updated_at":datetime.now()}
        r=tasks.insert_one(data)
        if data["assigned_to"]: notify(data["assigned_to"],f"New task assigned: {data['title']}","task")
        log("Task created",data["title"]); return redirect(url_for("task_list"))
    return render_template("task_form.html",task=None,projects=list(projects.find()),members=list(users.find({"status":"Active"})))

@app.route("/tasks/<id>/edit", methods=["GET","POST"])
@login_required
def task_edit(id):
    t=tasks.find_one({"_id":oid(id)})
    if not t: return redirect(url_for("task_list"))
    u=current_user()
    if request.method=="POST":
        data={"title":request.form["title"].strip(),"description":request.form.get("description",""),
              "project_id":request.form.get("project_id",""),"assigned_to":request.form.get("assigned_to",""),
              "priority":request.form.get("priority","Medium"),"status":request.form.get("status","To Do"),
              "progress":max(0,min(100,int(request.form.get("progress",0) or 0))),
              "start_date":request.form.get("start_date",""),"due_date":request.form.get("due_date",""),
              "updated_at":datetime.now()}
        # Employee may update only status/progress/comments through this screen.
        if u["role"]=="Employee":
            data={"status":data["status"],"progress":data["progress"],"description":data["description"],"updated_at":datetime.now()}
        tasks.update_one({"_id":t["_id"]},{"$set":data})
        if data.get("status")=="Completed" and t.get("status")!="Completed":
            notify(t.get("created_by"),f"Task completed: {t['title']}","success")
        log("Task updated",t["title"]); return redirect(url_for("task_list"))
    return render_template("task_form.html",task=t,projects=list(projects.find()),members=list(users.find({"status":"Active"})),comments=list(comments.find({"task_id":str(t["_id"])}).sort("created_at",DESCENDING)))

@app.route("/tasks/<id>/delete", methods=["POST"])
@roles("Admin","Project Manager","Team Lead")
def task_delete(id):
    t=tasks.find_one({"_id":oid(id)})
    if t: tasks.delete_one({"_id":t["_id"]}); comments.delete_many({"task_id":str(t["_id"])}); log("Task deleted",t["title"])
    return redirect(url_for("task_list"))

@app.route("/tasks/<id>/comment", methods=["POST"])
@login_required
def task_comment(id):
    text=request.form.get("comment","").strip()
    if text:
        comments.insert_one({"task_id":id,"user_id":str(current_user()["_id"]),
                             "user_name":current_user()["name"],"text":text,"created_at":datetime.now()})
        t=tasks.find_one({"_id":oid(id)})
        if t: notify(t.get("created_by"),f"New comment on task: {t['title']}","comment")
    return redirect(url_for("task_list"))

@app.route("/notifications")
@login_required
def notification_list():
    uid=str(current_user()["_id"])
    ns=list(notifications.find({"user_id":uid}).sort("created_at",DESCENDING).limit(50))
    return render_template("notifications.html",notifications=ns)

@app.route("/notifications/read", methods=["POST"])
@login_required
def notification_read():
    notifications.update_many({"user_id":str(current_user()["_id"])},{"$set":{"read":True}})
    return redirect(url_for("notification_list"))

@app.route("/reports")
@roles("Admin","Project Manager","Team Lead")
def reports():
    all_tasks=list(tasks.find())
    all_projects=list(projects.find())
    by_user=[]
    for u in users.find({"role":"Employee"}):
        uid=str(u["_id"]); mine=[t for t in all_tasks if t.get("assigned_to")==uid]
        by_user.append({"name":u["name"],"total":len(mine),"completed":sum(t.get("status")=="Completed" for t in mine),
                         "progress":round(sum(t.get("progress",0) for t in mine)/len(mine)) if mine else 0})
    return render_template("reports.html",projects=all_projects,tasks=all_tasks,by_user=by_user)

@app.route("/reports/export.csv")
@roles("Admin","Project Manager","Team Lead")
def export_csv():
    out=io.StringIO(); w=csv.writer(out)
    w.writerow(["Task","Project","Assigned To","Priority","Status","Progress","Due Date"])
    for t in tasks.find():
        p=projects.find_one({"_id":oid(t.get("project_id"))})
        u=users.find_one({"_id":oid(t.get("assigned_to"))})
        w.writerow([t.get("title",""),p.get("name","") if p else "",u.get("name","") if u else "",
                    t.get("priority",""),t.get("status",""),t.get("progress",0),t.get("due_date","")])
    r=make_response(out.getvalue()); r.headers["Content-Disposition"]="attachment; filename=task_report.csv"; r.headers["Content-Type"]="text/csv"
    return r

@app.route("/logs")
@roles("Admin")
def activity_logs():
    return render_template("logs.html",logs=list(logs.find().sort("created_at",DESCENDING).limit(100)))

@app.route("/api/stats")
@login_required
def api_stats():
    return jsonify({"users":users.count_documents({}),"projects":projects.count_documents({}),
                    "tasks":tasks.count_documents({}),"completed":tasks.count_documents({"status":"Completed"}),
                    "pending":tasks.count_documents({"status":{"$ne":"Completed"}})})

@app.route("/api/tasks")
@login_required
def api_tasks():
    data=[]
    for t in tasks.find().sort("created_at",DESCENDING).limit(100):
        data.append({"id":str(t["_id"]),"title":t.get("title"),"status":t.get("status"),
                     "priority":t.get("priority"),"progress":t.get("progress",0),"due_date":t.get("due_date")})
    return jsonify(data)

@app.errorhandler(404)
def not_found(e): return render_template("error.html",code=404,message="Page not found"),404

@app.errorhandler(500)
def server_error(e): return render_template("error.html",code=500,message="Server error"),500

if __name__=="__main__":
    app.run(host="0.0.0.0",port=5000,debug=True)
