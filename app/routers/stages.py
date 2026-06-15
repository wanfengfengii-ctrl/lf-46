from fastapi import APIRouter, Depends, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from ..database import get_db

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def index(request: Request, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("""
        SELECT s.*, 
            (SELECT COUNT(*) FROM measurement_points WHERE stage_id = s.id) as point_count,
            (SELECT COUNT(*) FROM measurement_sessions WHERE stage_id = s.id) as session_count
        FROM stages s ORDER BY s.created_at DESC
    """)
    stages = [dict(row) for row in cursor.fetchall()]
    return templates.TemplateResponse("index.html", {"request": request, "stages": stages})


@router.post("/stages/create")
def create_stage(request: Request, name: str = Form(...), location: str = Form(""),
                 description: str = Form(""), plan_width: float = Form(20.0),
                 plan_height: float = Form(15.0), db=Depends(get_db)):
    if not name.strip():
        raise HTTPException(status_code=400, detail="戏台名称不能为空")
    if plan_width <= 0:
        raise HTTPException(status_code=400, detail="平面宽度必须大于0")
    if plan_height <= 0:
        raise HTTPException(status_code=400, detail="平面高度必须大于0")
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO stages (name, location, description, plan_width, plan_height) VALUES (?, ?, ?, ?, ?)",
        (name.strip(), location.strip(), description.strip(), plan_width, plan_height),
    )
    db.commit()
    return RedirectResponse(url="/", status_code=303)


@router.get("/stages/{stage_id}", response_class=HTMLResponse)
def stage_detail(request: Request, stage_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM stages WHERE id = ?", (stage_id,))
    stage = cursor.fetchone()
    if not stage:
        raise HTTPException(status_code=404, detail="戏台不存在")
    stage = dict(stage)

    cursor.execute("SELECT * FROM measurement_points WHERE stage_id = ? ORDER BY label", (stage_id,))
    points = [dict(row) for row in cursor.fetchall()]

    cursor.execute("""
        SELECT ms.*, 
            (SELECT COUNT(*) FROM acoustic_data WHERE session_id = ms.id) as data_count
        FROM measurement_sessions ms WHERE ms.stage_id = ? ORDER BY ms.created_at DESC
    """, (stage_id,))
    sessions = [dict(row) for row in cursor.fetchall()]

    cursor.execute("SELECT * FROM conclusions WHERE stage_id = ? ORDER BY created_at DESC", (stage_id,))
    conclusions = [dict(row) for row in cursor.fetchall()]

    cursor.execute("""
        SELECT mt.*,
               (SELECT COUNT(*) FROM task_equipment te WHERE te.task_id = mt.id) as equipment_count,
               (SELECT COUNT(*) FROM measurement_sessions ms WHERE ms.task_id = mt.id) as session_count
        FROM measurement_tasks mt
        WHERE mt.stage_id = ?
        ORDER BY mt.created_at DESC
    """, (stage_id,))
    tasks = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse("stage_detail.html", {
        "request": request, "stage": stage, "points": points,
        "sessions": sessions, "conclusions": conclusions, "tasks": tasks,
    })


@router.post("/stages/{stage_id}/delete")
def delete_stage(stage_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT id FROM stages WHERE id = ?", (stage_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="戏台不存在")
    cursor.execute("DELETE FROM stages WHERE id = ?", (stage_id,))
    db.commit()
    return RedirectResponse(url="/", status_code=303)
