from fastapi import FastAPI, HTTPException, Depends, Request
from pydantic import BaseModel, Field, EmailStr, validator
from typing import List, Optional
import os
from datetime import datetime, timezone, timedelta
import logging
from fastapi.middleware.cors import CORSMiddleware
from groq import Groq
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, Session, relationship, declarative_base
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import func
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import OAuth2PasswordBearer
import hashlib
from sqlalchemy.sql.schema import MetaData
import json
import re

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler("app.log")])
logger = logging.getLogger(__name__)

app = FastAPI()

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# MySQL database setup
Base = declarative_base()
metadata = MetaData()

class User(Base):
    __tablename__ = "users"
    __table_args__ = {'mysql_engine': 'InnoDB'}
    user_id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now(timezone.utc))
    tasks = relationship("Task", back_populates="user")

class Category(Base):
    __tablename__ = "categories"
    __table_args__ = {'mysql_engine': 'InnoDB'}
    category_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False)
    color = Column(String(7), nullable=False)
    tasks = relationship("Task", back_populates="category")

class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = {'mysql_engine': 'InnoDB'}
    task_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.category_id", ondelete="SET NULL"), nullable=True)
    description = Column(String(255), nullable=False)
    due_date = Column(String(10), nullable=True)
    priority = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False)
    insights = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False)
    user = relationship("User", back_populates="tasks")
    category = relationship("Category", back_populates="tasks")
    tags = relationship("TaskTag", back_populates="task", cascade="all, delete-orphan")
    history = relationship("TaskHistory", back_populates="task", cascade="all, delete-orphan")

class TaskTag(Base):
    __tablename__ = "task_tags"
    __table_args__ = {'mysql_engine': 'InnoDB'}
    task_id = Column(Integer, ForeignKey("tasks.task_id", ondelete="CASCADE"), primary_key=True)
    tag_name = Column(String(50), primary_key=True)
    task = relationship("Task", back_populates="tags")

class TaskHistory(Base):
    __tablename__ = "task_history"
    __table_args__ = {'mysql_engine': 'InnoDB'}
    history_id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("tasks.task_id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    action = Column(String(50), nullable=False)
    details = Column(String(255), nullable=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.now(timezone.utc))
    task = relationship("Task", back_populates="history")
    user = relationship("User")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "task_manager")
DB_PORT = os.getenv("DB_PORT", 3306)

SQLALCHEMY_DATABASE_URL = f"mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

try:
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
    with engine.connect() as connection:
        logger.info("Successfully connected to MySQL database")
except Exception as e:
    logger.error(f"Failed to connect to MySQL database: {e}")
    raise

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create tables
Base.metadata.create_all(bind=engine)

# Dependency for database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Basic user authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == token).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    return user

# Groq client configuration
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    logger.error("GROQ_API_KEY not found in environment variables")
    raise ValueError("GROQ_API_KEY is required")
client = Groq(api_key=GROQ_API_KEY)

class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str

class CategoryCreate(BaseModel):
    name: str
    color: str = Field(..., pattern="^#[0-9A-Fa-f]{6}$")

class TaskQuery(BaseModel):
    query: str

class TaskManual(BaseModel):
    description: str
    due_date: Optional[str] = None
    category_id: Optional[int] = None
    tags: List[str] = []
    priority: str = Field(default="Medium", pattern="^(Urgent|Very high|High|Medium|Low|Very low)$")
    status: str = Field(default="Incomplete", pattern="^(Incomplete|In Progress|Completed)$")
    insights: Optional[str] = None

    @validator("due_date")
    def validate_due_date(cls, v):
        if v and not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError("due_date must be in YYYY-MM-DD format")
        return v

class TaskUpdate(BaseModel):
    status: Optional[str] = Field(None, pattern="^(Incomplete|In Progress|Completed)$")
    category_id: Optional[int] = None

class TaskSearch(BaseModel):
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    category_id: Optional[int] = None
    priority: Optional[str] = None
    status: Optional[str] = None

def task_to_dict(task):
    return {
        "task_id": task.task_id,
        "user_id": task.user_id,
        "category_id": task.category_id,
        "category_name": task.category.name if task.category else None,
        "category_color": task.category.color if task.category else None,
        "description": task.description,
        "due_date": task.due_date,
        "tags": [tag.tag_name for tag in task.tags],
        "priority": task.priority,
        "status": task.status,
        "insights": task.insights,
        "created_at": task.created_at.isoformat()
    }

def query_groq(prompt: str) -> dict:
    try:
        response = client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[
                {"role": "system", "content": "You are a task management assistant. Return a valid JSON object with no comments or explanatory text: {description: string, due_date: string (YYYY-MM-DD or relative like 'tomorrow'), tags: string[], priority: string (Urgent, Very high, High, Medium, Low, Very low), insights: string, category: string}."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=500,
            temperature=0.5
        )
        return response.to_dict()
    except Exception as e:
        logger.error(f"Groq API request failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Groq API error: {str(e)}")

def parse_query(query: str, db: Session) -> dict:
    query_normalized = query.replace("assigment", "assignment")
    prompt = f"""
    Analyze the following query and extract task details:
    Query: "{query_normalized}"
    Return a valid JSON object with:
    - description: Task description (string)
    - due_date: Due date in YYYY-MM-DD format or relative (e.g., 'tomorrow') (string, null if not mentioned)
    - tags: List of relevant tags (array of strings)
    - priority: Priority (Urgent, Very high, High, Medium, Low, Very low) (string)
    - insights: Suggestions for task management (string)
    - category: Suggested category name (string)
    Example:
    {{
        "description": "Complete my project",
        "due_date": "2025-05-20",
        "tags": ["project", "urgent"],
        "priority": "Medium",
        "insights": "Break into milestones: planning, execution, review.",
        "category": "Work"
    }}
    """
    try:
        result = query_groq(prompt)
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        
        json_match = re.search(r'\{[\s\S]*?\}', content, re.MULTILINE)
        if not json_match:
            raise ValueError("No JSON block found in response")
        
        json_str = json_match.group(0).strip()
        parsed_data = json.loads(json_str)
        
        current_date = datetime.now(timezone.utc)
        due_date = parsed_data.get("due_date")
        if due_date == "tomorrow":
            due_date = (current_date + timedelta(days=1)).strftime("%Y-%m-%d")
        elif due_date in ["in 2 days", "day after tomorrow"]:
            due_date = (current_date + timedelta(days=2)).strftime("%Y-%m-%d")
        elif due_date == "this friday":
            days_until_friday = (4 - current_date.weekday() + 7) % 7 or 7
            due_date = (current_date + timedelta(days=days_until_friday)).strftime("%Y-%m-%d")
        elif due_date == "this weekend":
            days_until_sunday = (6 - current_date.weekday() + 7) % 7 or 7
            due_date = (current_date + timedelta(days=days_until_sunday)).strftime("%Y-%m-%d")
        elif due_date == "today":
            due_date = current_date.strftime("%Y-%m-%d")
        parsed_data["due_date"] = due_date
        
        category_name = parsed_data.get("category")
        category_id = None
        if category_name:
            category = db.query(Category).filter(Category.name == category_name).first()
            if category:
                category_id = category.category_id
            else:
                new_category = Category(name=category_name, color="#4B5EAA")
                db.add(new_category)
                db.commit()
                db.refresh(new_category)
                category_id = new_category.category_id
        parsed_data["category_id"] = category_id
        
        return parsed_data
    except (HTTPException, json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Groq API parsing failed, falling back: {e}")
        due_date = None
        tags = []
        priority = "Medium"
        insights = "Manually created task due to API unavailability."
        category_id = None
        
        query_lower = query_normalized.lower()
        current_date = datetime.now(timezone.utc)
        if "tomorrow" in query_lower:
            due_date = (current_date + timedelta(days=1)).strftime("%Y-%m-%d")
            priority = "Urgent"
        elif "this friday" in query_lower:
            days_until_friday = (4 - current_date.weekday() + 7) % 7 or 7
            due_date = (current_date + timedelta(days=days_until_friday)).strftime("%Y-%m-%d")
            priority = "High"
        elif "this weekend" in query_lower:
            days_until_sunday = (6 - current_date.weekday() + 7) % 7 or 7
            due_date = (current_date + timedelta(days=days_until_sunday)).strftime("%Y-%m-%d")
            priority = "Medium"
        elif "today" in query_lower:
            due_date = current_date.strftime("%Y-%m-%d")
            priority = "Urgent"
        
        if "college" in query_lower:
            tags.append("college")
            category_name = "School"
            category = db.query(Category).filter(Category.name == category_name).first()
            if category:
                category_id = category.category_id
        if "assignment" in query_lower:
            tags.append("assignment")
            category_name = "School"
            category = db.query(Category).filter(Category.name == category_name).first()
            if category:
                category_id = category.category_id
        if "project" in query_lower:
            tags.append("project")
            category_name = "Work"
            category = db.query(Category).filter(Category.name == category_name).first()
            if category:
                category_id = category.category_id
        if "urgent" in query_lower:
            priority = "Urgent"
        
        return {
            "description": query_normalized,
            "due_date": due_date,
            "tags": tags,
            "priority": priority,
            "insights": insights,
            "category_id": category_id
        }

@app.get("/", response_class=HTMLResponse)
async def root():
    try:
        with open("static/index.html", "r") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="index.html not found")

@app.get("/test-groq")
async def test_groq():
    try:
        result = query_groq("Test query for Groq API")
        logger.info(f"Test Groq response: {json.dumps(result, indent=2)}")
        return {"message": "Groq API test successful", "response": result}
    except Exception as e:
        logger.error(f"Test Groq failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/users/register")
async def register_user(user: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.username == user.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists")
    new_user = User(username=user.username, email=user.email, password_hash=hash_password(user.password), created_at=datetime.now(timezone.utc))
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    logger.info(f"Registered user: {user.username}")
    return {"message": f"User {user.username} registered successfully", "token": user.username}

@app.post("/login")
async def login(login_request: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == login_request.username).first()
    if not user or user.password_hash != hash_password(login_request.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    logger.info(f"User logged in: {login_request.username}")
    return {"message": "Login successful", "token": user.username}

@app.post("/categories")
async def create_category(category: CategoryCreate, db: Session = Depends(get_db)):
    new_category = Category(name=category.name, color=category.color)
    db.add(new_category)
    db.commit()
    db.refresh(new_category)
    logger.info(f"Created category: {category.name}")
    return {"category_id": new_category.category_id, "name": new_category.name, "color": new_category.color}

@app.get("/categories")
async def get_categories(db: Session = Depends(get_db)):
    categories = db.query(Category).all()
    return [{"category_id": c.category_id, "name": c.name, "color": c.color} for c in categories]

@app.post("/tasks/query")
async def create_task_from_query(task_query: TaskQuery, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task_data = parse_query(task_query.query, db)
    new_task = Task(
        user_id=user.user_id,
        category_id=task_data.get("category_id"),
        description=task_data["description"],
        due_date=task_data.get("due_date"),
        priority=task_data.get("priority", "Medium"),
        status="Incomplete",
        insights=task_data.get("insights"),
        created_at=datetime.now(timezone.utc)
    )
    db.add(new_task)
    db.commit()
    db.refresh(new_task)
    for tag in task_data.get("tags", []):
        db.add(TaskTag(task_id=new_task.task_id, tag_name=tag))
    db.add(TaskHistory(task_id=new_task.task_id, user_id=user.user_id, action="created", details=f"Task created via query: {task_query.query}", timestamp=datetime.now(timezone.utc)))
    db.commit()
    logger.info(f"Created task via query: {new_task.task_id}")
    return task_to_dict(new_task)

@app.post("/tasks/manual")
async def create_task_manual(task: TaskManual, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    new_task = Task(
        user_id=user.user_id,
        category_id=task.category_id,
        description=task.description,
        due_date=task.due_date,
        priority=task.priority,
        status=task.status,
        insights=task.insights,
        created_at=datetime.now(timezone.utc)
    )
    db.add(new_task)
    db.commit()
    db.refresh(new_task)
    for tag in task.tags:
        db.add(TaskTag(task_id=new_task.task_id, tag_name=tag))
    db.add(TaskHistory(task_id=new_task.task_id, user_id=user.user_id, action="created", details="Task created manually", timestamp=datetime.now(timezone.utc)))
    db.commit()
    logger.info(f"Created manual task: {new_task.task_id}")
    return task_to_dict(new_task)

@app.post("/tasks/search")
async def search_tasks(search: TaskSearch, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(Task).filter(Task.user_id == user.user_id)
    if search.description:
        query = query.filter(Task.description.ilike(f"%{search.description}%"))
    if search.category_id:
        query = query.filter(Task.category_id == search.category_id)
    if search.priority:
        query = query.filter(Task.priority == search.priority)
    if search.status:
        query = query.filter(Task.status == search.status)
    if search.tags:
        query = query.join(TaskTag).filter(TaskTag.tag_name.in_(search.tags))
    tasks = query.order_by(func.coalesce(Task.due_date, '9999-12-31')).all()
    logger.info(f"Search tasks returned {len(tasks)} results for user {user.user_id}")
    return [task_to_dict(task) for task in tasks]

@app.get("/tasks")
async def get_tasks(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    tasks = db.query(Task).filter(Task.user_id == user.user_id).order_by(func.coalesce(Task.due_date, '9999-12-31')).all()
    logger.info(f"Fetched {len(tasks)} tasks for user {user.user_id}")
    return [task_to_dict(task) for task in tasks]

@app.put("/tasks/{task_id}")
async def update_task(task_id: int, task_update: TaskUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = db.query(Task).filter(Task.task_id == task_id, Task.user_id == user.user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task_update.status:
        task.status = task_update.status
    if task_update.category_id is not None:
        task.category_id = task_update.category_id
    db.commit()
    db.refresh(task)
    db.add(TaskHistory(task_id=task.task_id, user_id=user.user_id, action="updated", details=f"Updated status to {task_update.status}, category to {task_update.category_id}", timestamp=datetime.now(timezone.utc)))
    db.commit()
    logger.info(f"Updated task {task_id} for user {user.user_id}")
    return task_to_dict(task)

@app.delete("/tasks/{task_id}")
async def delete_task(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = db.query(Task).filter(Task.task_id == task_id, Task.user_id == user.user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    # Log the task and its relationships before deletion
    logger.info(f"Deleting task {task_id} for user {user.user_id}")
    logger.info(f"Task has {len(task.tags)} tags and {len(task.history)} history entries")
    # Add history entry
    db.add(TaskHistory(task_id=task.task_id, user_id=user.user_id, action="deleted", details="Task deleted", timestamp=datetime.now(timezone.utc)))
    # Delete the task (related tags and history should cascade)
    db.delete(task)
    db.commit()
    logger.info(f"Successfully deleted task {task_id}")
    return {"message": f"Task {task_id} deleted"}

@app.get("/task_history/{task_id}")
async def get_task_history(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = db.query(Task).filter(Task.task_id == task_id, Task.user_id == user.user_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    history = db.query(TaskHistory).filter(TaskHistory.task_id == task_id).order_by(TaskHistory.timestamp.desc()).all()
    logger.info(f"Fetched history for task {task_id}")
    return [{"history_id": h.history_id, "task_id": h.task_id, "user_id": h.user_id, "action": h.action, "details": h.details, "timestamp": h.timestamp.isoformat()} for h in history]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)