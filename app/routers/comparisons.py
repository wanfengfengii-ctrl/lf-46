from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from ..database import get_db
from ..validators import validate_same_stage

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/stages/{stage_id}/heatmap/{session_id}", response_class=HTMLResponse)
def heatmap_page(request: Request, stage_id: int, session_id: int, db=Depends(get_db)):
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

    cursor.execute("""
        SELECT ad.*, mp.label as point_label, mp.x, mp.y
        FROM acoustic_data ad
        JOIN measurement_points mp ON ad.point_id = mp.id
        WHERE ad.session_id = ?
        ORDER BY mp.label
    """, (session_id,))
    data_rows = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse("heatmap.html", {
        "request": request, "stage": stage, "session": session, "data_rows": data_rows,
    })


@router.get("/stages/{stage_id}/compare", response_class=HTMLResponse)
def compare_page(request: Request, stage_id: int, sessions: str = "", db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM stages WHERE id = ?", (stage_id,))
    stage = cursor.fetchone()
    if not stage:
        raise HTTPException(status_code=404, detail="戏台不存在")
    stage = dict(stage)

    cursor.execute("SELECT * FROM measurement_sessions WHERE stage_id = ? ORDER BY created_at DESC", (stage_id,))
    all_sessions = [dict(row) for row in cursor.fetchall()]

    selected_session_ids = []
    if sessions:
        try:
            selected_session_ids = [int(s.strip()) for s in sessions.split(",") if s.strip()]
        except ValueError:
            pass

    comparison_data = []
    comparison_error = None

    if len(selected_session_ids) >= 2:
        try:
            validate_same_stage(selected_session_ids, db)
        except HTTPException as e:
            comparison_error = e.detail

        if not comparison_error:
            for sid in selected_session_ids:
                cursor.execute("SELECT * FROM measurement_sessions WHERE id = ?", (sid,))
                sess = cursor.fetchone()
                if not sess:
                    continue
                sess = dict(sess)

                cursor.execute("""
                    SELECT ad.*, mp.label as point_label, mp.x, mp.y
                    FROM acoustic_data ad
                    JOIN measurement_points mp ON ad.point_id = mp.id
                    WHERE ad.session_id = ?
                    ORDER BY mp.label
                """, (sid,))
                rows = [dict(row) for row in cursor.fetchall()]
                comparison_data.append({"session": sess, "data": rows})

    diff_table = None
    if len(comparison_data) == 2:
        s1_map = {d["point_label"]: d for d in comparison_data[0]["data"]}
        s2_map = {d["point_label"]: d for d in comparison_data[1]["data"]}
        all_labels = sorted(set(s1_map.keys()) | set(s2_map.keys()))
        diff_table = []
        for label in all_labels:
            d1 = s1_map.get(label)
            d2 = s2_map.get(label)
            row = {"label": label, "d1": d1, "d2": d2}
            if d1 and d2 and d1.get("sound_pressure") is not None and d2.get("sound_pressure") is not None:
                row["sp_diff"] = round(d2["sound_pressure"] - d1["sound_pressure"], 2)
            else:
                row["sp_diff"] = None
            if d1 and d2 and d1.get("reverberation_time") is not None and d2.get("reverberation_time") is not None:
                row["rt_diff"] = round(d2["reverberation_time"] - d1["reverberation_time"], 3)
            else:
                row["rt_diff"] = None
            if d1 and d2 and d1.get("speech_clarity") is not None and d2.get("speech_clarity") is not None:
                row["sc_diff"] = round(d2["speech_clarity"] - d1["speech_clarity"], 3)
            else:
                row["sc_diff"] = None
            diff_table.append(row)

    return templates.TemplateResponse("comparison.html", {
        "request": request, "stage": stage, "all_sessions": all_sessions,
        "selected_session_ids": selected_session_ids,
        "comparison_data": comparison_data, "comparison_error": comparison_error,
        "diff_table": diff_table,
    })


@router.get("/api/stages/{stage_id}/heatmap-data/{session_id}")
def heatmap_data_api(stage_id: int, session_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("""
        SELECT ad.sound_pressure, ad.reverberation_time, ad.speech_clarity,
               mp.x, mp.y, mp.label
        FROM acoustic_data ad
        JOIN measurement_points mp ON ad.point_id = mp.id
        WHERE ad.session_id = ?
        ORDER BY mp.label
    """, (session_id,))
    rows = [dict(row) for row in cursor.fetchall()]
    return {"data": rows}


@router.get("/api/stages/{stage_id}/comparison-data")
def comparison_data_api(stage_id: int, sessions: str, db=Depends(get_db)):
    try:
        session_ids = [int(s.strip()) for s in sessions.split(",") if s.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的场次ID")

    validate_same_stage(session_ids, db)

    result = []
    for sid in session_ids:
        cursor = db.cursor()
        cursor.execute("SELECT * FROM measurement_sessions WHERE id = ?", (sid,))
        sess = cursor.fetchone()
        if not sess:
            continue
        sess = dict(sess)

        cursor.execute("""
            SELECT ad.sound_pressure, ad.reverberation_time, ad.speech_clarity,
                   mp.x, mp.y, mp.label
            FROM acoustic_data ad
            JOIN measurement_points mp ON ad.point_id = mp.id
            WHERE ad.session_id = ?
            ORDER BY mp.label
        """, (sid,))
        rows = [dict(row) for row in cursor.fetchall()]
        result.append({"session": sess, "data": rows})

    return {"comparisons": result}
