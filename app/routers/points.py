from fastapi import APIRouter, Depends, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from ..database import get_db
from ..validators import validate_coordinates, invalidate_heatmaps
from .versions import auto_create_version

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/stages/{stage_id}/points", response_class=HTMLResponse)
def points_page(request: Request, stage_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM stages WHERE id = ?", (stage_id,))
    stage = cursor.fetchone()
    if not stage:
        raise HTTPException(status_code=404, detail="戏台不存在")
    stage = dict(stage)

    cursor.execute("SELECT * FROM measurement_points WHERE stage_id = ? ORDER BY label", (stage_id,))
    points = [dict(row) for row in cursor.fetchall()]
    return templates.TemplateResponse("points.html", {"request": request, "stage": stage, "points": points})


@router.post("/stages/{stage_id}/points/create")
def create_point(request: Request, stage_id: int, label: str = Form(...),
                 x: float = Form(...), y: float = Form(...), db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT id FROM stages WHERE id = ?", (stage_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="戏台不存在")

    validate_coordinates(stage_id, x, y, db)

    cursor.execute(
        "INSERT INTO measurement_points (stage_id, label, x, y) VALUES (?, ?, ?, ?)",
        (stage_id, label.strip(), x, y),
    )
    db.commit()
    auto_create_version(stage_id, db, created_by="系统", modification_description=f"新增测量点: {label.strip()}")
    return RedirectResponse(url=f"/stages/{stage_id}/points", status_code=303)


@router.post("/stages/{stage_id}/points/{point_id}/edit")
def edit_point(request: Request, stage_id: int, point_id: int, label: str = Form(...),
               x: float = Form(...), y: float = Form(...), db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT id FROM measurement_points WHERE id = ? AND stage_id = ?", (point_id, stage_id))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="测量点不存在")

    validate_coordinates(stage_id, x, y, db, exclude_point_id=point_id)

    cursor.execute(
        "SELECT session_id FROM acoustic_data WHERE point_id = ?",
        (point_id,),
    )
    affected_sessions = [row["session_id"] for row in cursor.fetchall()]

    cursor.execute(
        "UPDATE measurement_points SET label = ?, x = ?, y = ? WHERE id = ?",
        (label.strip(), x, y, point_id),
    )

    for sid in affected_sessions:
        invalidate_heatmaps(sid, db)

    db.commit()
    auto_create_version(stage_id, db, created_by="系统", modification_description=f"修改测量点: {label.strip()}")
    return RedirectResponse(url=f"/stages/{stage_id}/points", status_code=303)


@router.post("/stages/{stage_id}/points/{point_id}/delete")
def delete_point(stage_id: int, point_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT id, label FROM measurement_points WHERE id = ? AND stage_id = ?", (point_id, stage_id))
    point = cursor.fetchone()
    if not point:
        raise HTTPException(status_code=404, detail="测量点不存在")
    point_label = point["label"]
    cursor.execute("DELETE FROM measurement_points WHERE id = ?", (point_id,))
    db.commit()
    auto_create_version(stage_id, db, created_by="系统", modification_description=f"删除测量点: {point_label}")
    return RedirectResponse(url=f"/stages/{stage_id}/points", status_code=303)
