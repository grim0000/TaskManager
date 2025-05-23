# AI Task Manager

A modern task management system powered by FastAPI, React, and Groq LLM.

## Features

- Natural language task creation using Groq LLM
- Task categorization and tagging
- Priority and status management
- Task history tracking
- Responsive UI built with React and Tailwind CSS
- User authentication
- MySQL database integration

## Tech Stack

- **Backend**: FastAPI (Python)
- **Frontend**: React + Tailwind CSS
- **Database**: MySQL
- **AI**: Groq LLM API
- **Authentication**: OAuth2 with Password Bearer

## Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/task-manager.git
cd task-manager
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file in the project root:
```properties
GROQ_API_KEY=your_groq_api_key
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=your_db_password
DB_NAME=task_manager
DB_PORT=3306
```

5. Initialize the MySQL database using xampp:
```sql
CREATE DATABASE task_manager;
```

6. Run the application:
```bash
uvicorn main:app --reload
```

7. Open http://localhost:8000 in your browser

## API Documentation

Once the server is running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Project Structure

```
task-manager/
├── static/
│   └── index.html      # React frontend
├── main.py             # FastAPI application
├── requirements.txt    # Python dependencies
├── .env               # Environment variables
└── README.md          # Project documentation
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.
