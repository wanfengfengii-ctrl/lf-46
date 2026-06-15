import csv
import io
from typing import Optional
from fastapi import APIRouter, Depends, Request, HTTPException, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from ..database import get_db
from ..validators import validate_acoustic_values, invalidate_heatmaps

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.post("/stages/{stage_id}/sessions/{session_id}/data/save")
def save_acoustic_data(request: Request, stage_id: int, session_id: int,
                       point_id: int = Form(...),
                       sound_pressure: Optional[float] = Form(None),
                       reverberation_time: Optional[float] = Form(None),
                       speech_clarity: Optional[float] = Form(None),
                       notes: str = Form(""), db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT id FROM measurement_sessions WHERE id = ? AND stage_id = ?", (session_id, stage_id))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="测量场次不存在")

    cursor.execute("SELECT id FROM measurement_points WHERE id = ? AND stage_id = ?", (point_id, stage_id))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="测量点不存在")

    validate_acoustic_values(sound_pressure, reverberation_time, speech_clarity)

    cursor.execute(
        "SELECT id FROM acoustic_data WHERE session_id = ? AND point_id = ?",
        (session_id, point_id),
    )
    existing = cursor.fetchone()

    if existing:
        cursor.execute(
            "UPDATE acoustic_data SET sound_pressure = ?, reverberation_time = ?, speech_clarity = ?, notes = ? WHERE session_id = ? AND point_id = ?",
            (sound_pressure, reverberation_time, speech_clarity, notes.strip(), session_id, point_id),
        )
    else:
        cursor.execute(
            "INSERT INTO acoustic_data (session_id, point_id, sound_pressure, reverberation_time, speech_clarity, notes) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, point_id, sound_pressure, reverberation_time, speech_clarity, notes.strip()),
        )

    invalidate_heatmaps(session_id, db)
    db.commit()
    return RedirectResponse(url=f"/stages/{stage_id}/sessions/{session_id}", status_code=303)


@router.post("/stages/{stage_id}/sessions/{session_id}/data/batch")
async def batch_import(request: Request, stage_id: int, session_id: int,
                       file: UploadFile = File(...), db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT id FROM measurement_sessions WHERE id = ? AND stage_id = ?", (session_id, stage_id))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="测量场次不存在")

    cursor.execute("SELECT id, label FROM measurement_points WHERE stage_id = ?", (stage_id,))
    points_by_label = {row["label"]: row["id"] for row in cursor.fetchall()}

    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    errors = []
    row_num = 1
    for row in reader:
        row_num += 1
        label = row.get("测量点标签", row.get("point_label", "")).strip()
        if label not in points_by_label:
            errors.append(f"第{row_num}行: 测量点'{label}'不存在")
            continue

        point_id = points_by_label[label]
        sp_raw = row.get("声压", row.get("sound_pressure", "")).strip()
        rt_raw = row.get("混响时间", row.get("reverberation_time", "")).strip()
        sc_raw = row.get("语言清晰度", row.get("speech_clarity", "")).strip()

        sound_pressure = float(sp_raw) if sp_raw else None
        reverberation_time = float(rt_raw) if rt_raw else None
        speech_clarity = float(sc_raw) if sc_raw else None

        try:
            validate_acoustic_values(sound_pressure, reverberation_time, speech_clarity)
        except HTTPException as e:
            errors.append(f"第{row_num}行: {e.detail}")
            continue

        cursor.execute(
            "SELECT id FROM acoustic_data WHERE session_id = ? AND point_id = ?",
            (session_id, point_id),
        )
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                "UPDATE acoustic_data SET sound_pressure = ?, reverberation_time = ?, speech_clarity = ? WHERE session_id = ? AND point_id = ?",
                (sound_pressure, reverberation_time, speech_clarity, session_id, point_id),
            )
        else:
            cursor.execute(
                "INSERT INTO acoustic_data (session_id, point_id, sound_pressure, reverberation_time, speech_clarity) VALUES (?, ?, ?, ?, ?)",
                (session_id, point_id, sound_pressure, reverberation_time, speech_clarity),
            )

    invalidate_heatmaps(session_id, db)
    db.commit()

    if errors:
        raise HTTPException(status_code=400, detail="批量导入部分失败:\n" + "\n".join(errors))
    return RedirectResponse(url=f"/stages/{stage_id}/sessions/{session_id}", status_code=303)


@router.post("/stages/{stage_id}/sessions/{session_id}/data/{data_id}/delete")
def delete_acoustic_data(stage_id: int, session_id: int, data_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT id FROM acoustic_data WHERE id = ? AND session_id = ?", (data_id, session_id))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="声学数据不存在")
    cursor.execute("DELETE FROM acoustic_data WHERE id = ?", (data_id,))
    invalidate_heatmaps(session_id, db)
    db.commit()
    return RedirectResponse(url=f"/stages/{stage_id}/sessions/{session_id}", status_code=303)
