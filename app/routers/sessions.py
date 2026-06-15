from fastapi import APIRouter, Depends, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from ..database import get_db

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/stages/{stage_id}/sessions/create", response_class=HTMLResponse)
def create_session_page(request: Request, stage_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM stages WHERE id = ?", (stage_id,))
    stage = cursor.fetchone()
    if not stage:
        raise HTTPException(status_code=404, detail="戏台不存在")
    return templates.TemplateResponse("session_form.html", {"request": request, "stage": dict(stage), "session": None})


@router.post("/stages/{stage_id}/sessions/create")
def create_session(request: Request, stage_id: int, singer_position: str = Form("舞台中央"),
                   audience_count: int = Form(0), door_window_state: str = Form("closed"),
                   notes: str = Form(""), db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT id FROM stages WHERE id = ?", (stage_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="戏台不存在")
    if audience_count < 0:
        raise HTTPException(status_code=400, detail="观众数量不能为负数")

    cursor.execute(
        "INSERT INTO measurement_sessions (stage_id, singer_position, audience_count, door_window_state, notes) VALUES (?, ?, ?, ?, ?)",
        (stage_id, singer_position.strip(), audience_count, door_window_state, notes.strip()),
    )
    db.commit()
    return RedirectResponse(url=f"/stages/{stage_id}", status_code=303)


@router.get("/stages/{stage_id}/sessions/{session_id}", response_class=HTMLResponse)
def session_detail(request: Request, stage_id: int, session_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM stages WHERE id = ?", (stage_id,))
    stage = cursor.fetchone()
    if not stage:
        raise HTTPException(status_code=404, detail="戏台不存在")
    stage = dict(stage)

    cursor.execute("SELECT * FROM measurement_sessions WHERE id = ? AND stage_id = ?", (session_id, stage_id))
    session = cursor.fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="测量场次不存在")
    session = dict(session)

    cursor.execute("SELECT * FROM measurement_points WHERE stage_id = ? ORDER BY label", (stage_id,))
    points = [dict(row) for row in cursor.fetchall()]

    cursor.execute("""
        SELECT ad.*, mp.label as point_label, mp.x, mp.y
        FROM acoustic_data ad
        JOIN measurement_points mp ON ad.point_id = mp.id
        WHERE ad.session_id = ?
        ORDER BY mp.label
    """, (session_id,))
    data_rows = [dict(row) for row in cursor.fetchall()]

    data_map = {}
    for d in data_rows:
        data_map[d["point_id"]] = d

    return templates.TemplateResponse("session_detail.html", {
        "request": request, "stage": stage, "session": session,
        "points": points, "data_rows": data_rows, "data_map": data_map,
    })


@router.post("/stages/{stage_id}/sessions/{session_id}/delete")
def delete_session(stage_id: int, session_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT id FROM measurement_sessions WHERE id = ? AND stage_id = ?", (session_id, stage_id))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="测量场次不存在")
    cursor.execute("DELETE FROM measurement_sessions WHERE id = ?", (session_id,))
    db.commit()
    return RedirectResponse(url=f"/stages/{stage_id}", status_code=303)
