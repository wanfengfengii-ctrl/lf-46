from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from .database import init_db
from .routers import stages, points, sessions, acoustic, comparisons, conclusions, tasks

app = FastAPI(title="古戏台声学分析系统")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(stages.router)
app.include_router(points.router)
app.include_router(sessions.router)
app.include_router(acoustic.router)
app.include_router(comparisons.router)
app.include_router(conclusions.router)
app.include_router(tasks.router)


@app.on_event("startup")
def startup():
    init_db()
