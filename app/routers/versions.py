import json
import re
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Request, HTTPException, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from ..database import get_db

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def generate_version_number(stage_id: int, db) -> str:
    cursor = db.cursor()
    cursor.execute(
        "SELECT version_number FROM measurement_versions WHERE stage_id = ?",
        (stage_id,)
    )
    rows = cursor.fetchall()
    max_num = 0
    pattern = re.compile(r"^v(\d+)\.")
    for row in rows:
        m = pattern.match(row["version_number"])
        if m:
            num = int(m.group(1))
            if num > max_num:
                max_num = num
    return f"v{max_num + 1}.0"


def auto_create_version(
    stage_id: int,
    db,
    created_by: str = "系统",
    modification_description: str = "",
    data_source: str = "自动版本",
    session_id: int = None
) -> Optional[int]:
    cursor = db.cursor()
    cursor.execute("SELECT id FROM stages WHERE id = ?", (stage_id,))
    if not cursor.fetchone():
        return None

    cursor.execute(
        "SELECT id FROM measurement_versions WHERE stage_id = ? ORDER BY created_at DESC LIMIT 1",
        (stage_id,)
    )
    latest = cursor.fetchone()
    parent_version_id = latest["id"] if latest else None

    version_number = generate_version_number(stage_id, db)

    cursor.execute(
        "SELECT content, is_confirmed FROM conclusions WHERE stage_id = ? ORDER BY created_at DESC LIMIT 1",
        (stage_id,)
    )
    concl_row = cursor.fetchone()
    conclusion_snapshot = ""
    if concl_row:
        concl_data = {"content": concl_row["content"], "is_confirmed": concl_row["is_confirmed"]}
        conclusion_snapshot = json.dumps(concl_data, ensure_ascii=False)

    cursor.execute(
        """INSERT INTO measurement_versions 
           (stage_id, version_number, version_name, created_by, modification_description, 
            data_source, parent_version_id, session_id, conclusion_snapshot)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (stage_id, version_number, "", created_by,
         modification_description, data_source,
         parent_version_id, session_id, conclusion_snapshot)
    )
    version_id = cursor.lastrowid

    snapshot_points(version_id, stage_id, db, parent_version_id)
    snapshot_acoustic_data(version_id, stage_id, db, session_id, parent_version_id)
    generate_change_logs(version_id, stage_id, db, parent_version_id, session_id, modification_description)

    db.commit()
    return version_id


def snapshot_points(version_id: int, stage_id: int, db, parent_version_id: int = None):
    cursor = db.cursor()
    cursor.execute(
        "SELECT id, label, x, y FROM measurement_points WHERE stage_id = ? ORDER BY label",
        (stage_id,)
    )
    current_points = cursor.fetchall()
    current_map = {row["id"]: dict(row) for row in current_points}

    parent_points = {}
    if parent_version_id:
        cursor.execute(
            "SELECT point_id, label, x, y FROM version_point_snapshots WHERE version_id = ?",
            (parent_version_id,)
        )
        for row in cursor.fetchall():
            key = row["point_id"] if row["point_id"] else f"virtual_{row['label']}"
            parent_points[key] = dict(row)

    for pid, point in current_map.items():
        change_type = "unchanged"
        if pid in parent_points:
            pp = parent_points[pid]
            if (point["label"] != pp["label"] or
                abs(point["x"] - pp["x"]) > 1e-6 or
                abs(point["y"] - pp["y"]) > 1e-6):
                change_type = "modified"
        else:
            change_type = "added"

        cursor.execute(
            "INSERT INTO version_point_snapshots (version_id, point_id, label, x, y, change_type) VALUES (?, ?, ?, ?, ?, ?)",
            (version_id, pid, point["label"], point["x"], point["y"], change_type)
        )

    if parent_version_id:
        current_ids = set(current_map.keys())
        for pkey, pp in parent_points.items():
            pid = pp["point_id"]
            if pid and pid not in current_ids:
                cursor.execute(
                    "INSERT INTO version_point_snapshots (version_id, point_id, label, x, y, change_type) VALUES (?, ?, ?, ?, ?, ?)",
                    (version_id, pid, pp["label"], pp["x"], pp["y"], "removed")
                )


def snapshot_acoustic_data(version_id: int, stage_id: int, db, session_id: int = None, parent_version_id: int = None):
    cursor = db.cursor()

    if session_id:
        cursor.execute("""
            SELECT mp.label as point_label, ad.sound_pressure, ad.reverberation_time, 
                   ad.speech_clarity, ad.notes
            FROM acoustic_data ad
            JOIN measurement_points mp ON ad.point_id = mp.id
            WHERE ad.session_id = ?
            ORDER BY mp.label
        """, (session_id,))
    else:
        cursor.execute("""
            SELECT mp.label as point_label, ad.sound_pressure, ad.reverberation_time, 
                   ad.speech_clarity, ad.notes, ms.id as session_id
            FROM acoustic_data ad
            JOIN measurement_points mp ON ad.point_id = mp.id
            JOIN measurement_sessions ms ON ad.session_id = ms.id
            WHERE ms.stage_id = ?
            ORDER BY ms.created_at DESC, mp.label
        """, (stage_id,))

    current_rows = cursor.fetchall()
    current_map = {}
    for row in current_rows:
        label = row["point_label"]
        if label not in current_map:
            current_map[label] = dict(row)

    parent_map = {}
    if parent_version_id:
        cursor.execute(
            "SELECT point_label, sound_pressure, reverberation_time, speech_clarity, notes FROM version_acoustic_snapshots WHERE version_id = ?",
            (parent_version_id,)
        )
        for row in cursor.fetchall():
            parent_map[row["point_label"]] = dict(row)

    for label, data in current_map.items():
        change_type = "unchanged"
        if label in parent_map:
            pd = parent_map[label]
            sp_diff = abs((data["sound_pressure"] or 0) - (pd["sound_pressure"] or 0)) > 1e-6
            rt_diff = abs((data["reverberation_time"] or 0) - (pd["reverberation_time"] or 0)) > 1e-6
            sc_diff = abs((data["speech_clarity"] or 0) - (pd["speech_clarity"] or 0)) > 1e-6
            notes_diff = (data["notes"] or "") != (pd["notes"] or "")
            if sp_diff or rt_diff or sc_diff or notes_diff:
                change_type = "modified"
        else:
            change_type = "added"

        cursor.execute(
            """INSERT INTO version_acoustic_snapshots 
               (version_id, point_label, sound_pressure, reverberation_time, speech_clarity, notes, change_type) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (version_id, label, data["sound_pressure"], data["reverberation_time"],
             data["speech_clarity"], data.get("notes", ""), change_type)
        )

    if parent_version_id:
        current_labels = set(current_map.keys())
        for label, pd in parent_map.items():
            if label not in current_labels:
                cursor.execute(
                    """INSERT INTO version_acoustic_snapshots 
                       (version_id, point_label, sound_pressure, reverberation_time, speech_clarity, notes, change_type) 
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (version_id, label, pd["sound_pressure"], pd["reverberation_time"],
                     pd["speech_clarity"], pd.get("notes", ""), "removed")
                )


def compute_statistics(snapshots: list) -> dict:
    stats = {"sound_pressure": {}, "reverberation_time": {}, "speech_clarity": {}}
    sp_vals = [s["sound_pressure"] for s in snapshots if s["sound_pressure"] is not None]
    rt_vals = [s["reverberation_time"] for s in snapshots if s["reverberation_time"] is not None]
    sc_vals = [s["speech_clarity"] for s in snapshots if s["speech_clarity"] is not None]

    for name, vals in [("sound_pressure", sp_vals), ("reverberation_time", rt_vals), ("speech_clarity", sc_vals)]:
        if vals:
            stats[name]["count"] = len(vals)
            stats[name]["mean"] = round(sum(vals) / len(vals), 4)
            stats[name]["min"] = round(min(vals), 4)
            stats[name]["max"] = round(max(vals), 4)
            if len(vals) > 1:
                mean = sum(vals) / len(vals)
                variance = sum((v - mean) ** 2 for v in vals) / len(vals)
                stats[name]["std"] = round(variance ** 0.5, 4)
            else:
                stats[name]["std"] = 0
    return stats


def generate_change_logs(version_id: int, stage_id: int, db, parent_version_id: int = None,
                         session_id: int = None, modification_description: str = ""):
    cursor = db.cursor()
    logs = []

    if parent_version_id:
        cursor.execute(
            "SELECT change_type, COUNT(*) as cnt FROM version_point_snapshots WHERE version_id = ? GROUP BY change_type",
            (version_id,)
        )
        point_stats = {row["change_type"]: row["cnt"] for row in cursor.fetchall()}
        if point_stats.get("added", 0) > 0:
            logs.append(("测量点", f"新增 {point_stats['added']} 个测量点", None, None))
        if point_stats.get("modified", 0) > 0:
            logs.append(("测量点", f"修改 {point_stats['modified']} 个测量点", None, None))
        if point_stats.get("removed", 0) > 0:
            logs.append(("测量点", f"删除 {point_stats['removed']} 个测量点", None, None))

        cursor.execute(
            "SELECT change_type, COUNT(*) as cnt FROM version_acoustic_snapshots WHERE version_id = ? GROUP BY change_type",
            (version_id,)
        )
        ac_stats = {row["change_type"]: row["cnt"] for row in cursor.fetchall()}
        if ac_stats.get("added", 0) > 0:
            logs.append(("声学数据", f"新增 {ac_stats['added']} 个测点的声学数据", None, None))
        if ac_stats.get("modified", 0) > 0:
            logs.append(("声学数据", f"修改 {ac_stats['modified']} 个测点的声学数据", None, None))
        if ac_stats.get("removed", 0) > 0:
            logs.append(("声学数据", f"删除 {ac_stats['removed']} 个测点的声学数据", None, None))

    cursor.execute(
        "SELECT content, is_confirmed FROM conclusions WHERE stage_id = ? ORDER BY created_at DESC LIMIT 1",
        (stage_id,)
    )
    concl = cursor.fetchone()
    if concl:
        logs.append(("分析结论", f"结论快照已保存，确认状态: {'已确认' if concl['is_confirmed'] else '待确认'}", None, None))

    if session_id:
        logs.append(("数据来源", f"基于测量场次 #{session_id} 创建", None, None))

    if modification_description:
        logs.append(("修改说明", modification_description, None, None))

    for category, detail, old_val, new_val in logs:
        cursor.execute(
            "INSERT INTO version_change_logs (version_id, change_category, change_detail, old_value, new_value) VALUES (?, ?, ?, ?, ?)",
            (version_id, category, detail, old_val, new_val)
        )


def status_map_val(s):
    return {"pending": 0, "approved": 1, "rejected": 2}.get(s, -1)


def compare_two_versions(va_id: int, vb_id: int, stage_id: int, db) -> dict:
    cursor = db.cursor()

    cursor.execute("""
        SELECT mv.id, mv.version_number, mv.version_name, mv.created_at, 
               mv.created_by, mv.modification_description, mv.review_status,
               mv.conclusion_snapshot
        FROM measurement_versions mv WHERE mv.id = ? AND mv.stage_id = ?
    """, (va_id, stage_id))
    va = cursor.fetchone()
    cursor.execute("""
        SELECT mv.id, mv.version_number, mv.version_name, mv.created_at, 
               mv.created_by, mv.modification_description, mv.review_status,
               mv.conclusion_snapshot
        FROM measurement_versions mv WHERE mv.id = ? AND mv.stage_id = ?
    """, (vb_id, stage_id))
    vb = cursor.fetchone()

    if not va or not vb:
        raise HTTPException(status_code=404, detail="版本不存在")
    va = dict(va)
    vb = dict(vb)

    cursor.execute(
        "SELECT * FROM version_point_snapshots WHERE version_id = ? ORDER BY label",
        (va_id,)
    )
    va_points = {row["label"]: dict(row) for row in cursor.fetchall()}
    cursor.execute(
        "SELECT * FROM version_point_snapshots WHERE version_id = ? ORDER BY label",
        (vb_id,)
    )
    vb_points = {row["label"]: dict(row) for row in cursor.fetchall()}

    all_point_labels = sorted(set(list(va_points.keys()) + list(vb_points.keys())))
    point_diffs = []
    for label in all_point_labels:
        pa = va_points.get(label)
        pb = vb_points.get(label)
        status = "unchanged"
        if pa and pb:
            if (abs(pa["x"] - pb["x"]) > 1e-6 or abs(pa["y"] - pb["y"]) > 1e-6):
                status = "modified"
        elif pa and not pb:
            status = "removed_in_b"
        elif not pa and pb:
            status = "added_in_b"
        point_diffs.append({
            "label": label, "point_a": pa, "point_b": pb, "status": status
        })

    cursor.execute(
        "SELECT * FROM version_acoustic_snapshots WHERE version_id = ? ORDER BY point_label",
        (va_id,)
    )
    va_ac = {row["point_label"]: dict(row) for row in cursor.fetchall()}
    cursor.execute(
        "SELECT * FROM version_acoustic_snapshots WHERE version_id = ? ORDER BY point_label",
        (vb_id,)
    )
    vb_ac = {row["point_label"]: dict(row) for row in cursor.fetchall()}

    all_ac_labels = sorted(set(list(va_ac.keys()) + list(vb_ac.keys())))
    acoustic_diffs = []
    for label in all_ac_labels:
        aa = va_ac.get(label)
        ab = vb_ac.get(label)
        status = "unchanged"
        changes = []
        if aa and ab:
            for field in ["sound_pressure", "reverberation_time", "speech_clarity"]:
                a_val = aa.get(field)
                b_val = ab.get(field)
                if (a_val is None) != (b_val is None):
                    changes.append(field)
                elif a_val is not None and abs(a_val - b_val) > 1e-6:
                    changes.append(field)
            if aa.get("notes", "") != ab.get("notes", ""):
                changes.append("notes")
            if changes:
                status = "modified"
        elif aa and not ab:
            status = "removed_in_b"
        elif not aa and ab:
            status = "added_in_b"
        acoustic_diffs.append({
            "label": label, "acoustic_a": aa, "acoustic_b": ab,
            "status": status, "changes": changes
        })

    stats_a = compute_statistics(list(va_ac.values()))
    stats_b = compute_statistics(list(vb_ac.values()))

    def safe_diff(a, b):
        if a is None and b is None:
            return 0
        if a is None:
            return b
        if b is None:
            return -a
        return round(b - a, 4)

    stats_diff = {}
    for metric in ["sound_pressure", "reverberation_time", "speech_clarity"]:
        stats_diff[metric] = {}
        for key in ["mean", "min", "max", "std"]:
            a_val = stats_a.get(metric, {}).get(key)
            b_val = stats_b.get(metric, {}).get(key)
            stats_diff[metric][key] = safe_diff(a_val, b_val)

    def parse_conclusion(s):
        if not s:
            return None
        try:
            return json.loads(s)
        except:
            return None

    concl_a = parse_conclusion(va.get("conclusion_snapshot", ""))
    concl_b = parse_conclusion(vb.get("conclusion_snapshot", ""))
    conclusion_changed = (concl_a != concl_b)
    conclusion_needs_review = conclusion_changed or (
        status_map_val(va.get("review_status")) != status_map_val(vb.get("review_status"))
    )

    point_change_counts = {
        "added": sum(1 for d in point_diffs if d["status"] == "added_in_b"),
        "removed": sum(1 for d in point_diffs if d["status"] == "removed_in_b"),
        "modified": sum(1 for d in point_diffs if d["status"] == "modified"),
        "unchanged": sum(1 for d in point_diffs if d["status"] == "unchanged"),
    }
    acoustic_change_counts = {
        "added": sum(1 for d in acoustic_diffs if d["status"] == "added_in_b"),
        "removed": sum(1 for d in acoustic_diffs if d["status"] == "removed_in_b"),
        "modified": sum(1 for d in acoustic_diffs if d["status"] == "modified"),
        "unchanged": sum(1 for d in acoustic_diffs if d["status"] == "unchanged"),
    }

    return {
        "version_a": va, "version_b": vb,
        "point_diffs": point_diffs, "acoustic_diffs": acoustic_diffs,
        "stats_a": stats_a, "stats_b": stats_b, "stats_diff": stats_diff,
        "conclusion_a": concl_a, "conclusion_b": concl_b,
        "conclusion_changed": conclusion_changed,
        "conclusion_needs_review": conclusion_needs_review,
        "point_change_counts": point_change_counts,
        "acoustic_change_counts": acoustic_change_counts,
    }


@router.get("/stages/{stage_id}/versions", response_class=HTMLResponse)
def version_list(request: Request, stage_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM stages WHERE id = ?", (stage_id,))
    stage = cursor.fetchone()
    if not stage:
        raise HTTPException(status_code=404, detail="戏台不存在")
    stage = dict(stage)

    cursor.execute("""
        SELECT mv.*,
            (SELECT COUNT(*) FROM version_point_snapshots WHERE version_id = mv.id) as point_count,
            (SELECT COUNT(*) FROM version_acoustic_snapshots WHERE version_id = mv.id) as data_count,
            pv.version_number as parent_version_number
        FROM measurement_versions mv
        LEFT JOIN measurement_versions pv ON mv.parent_version_id = pv.id
        WHERE mv.stage_id = ?
        ORDER BY mv.created_at DESC
    """, (stage_id,))
    versions = [dict(row) for row in cursor.fetchall()]

    status_map = {
        "pending": "待审核",
        "approved": "已通过",
        "rejected": "已驳回"
    }
    for v in versions:
        v["review_status_text"] = status_map.get(v["review_status"], v["review_status"])

    cursor.execute("""
        SELECT ms.id, ms.singer_position, ms.audience_count, ms.door_window_state, ms.created_at
        FROM measurement_sessions ms
        WHERE ms.stage_id = ?
        ORDER BY ms.created_at DESC
    """, (stage_id,))
    sessions = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse("version_list.html", {
        "request": request, "stage": stage, "versions": versions, "sessions": sessions
    })


@router.post("/stages/{stage_id}/versions/create")
def create_version(
    request: Request,
    stage_id: int,
    version_name: str = Form(""),
    created_by: str = Form(""),
    modification_description: str = Form(""),
    data_source: str = Form(""),
    parent_version_id: Optional[int] = Form(None),
    session_id: Optional[int] = Form(None),
    db=Depends(get_db)
):
    cursor = db.cursor()
    cursor.execute("SELECT id FROM stages WHERE id = ?", (stage_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="戏台不存在")

    if parent_version_id:
        cursor.execute(
            "SELECT id FROM measurement_versions WHERE id = ? AND stage_id = ?",
            (parent_version_id, stage_id)
        )
        if not cursor.fetchone():
            parent_version_id = None

    if session_id:
        cursor.execute(
            "SELECT id FROM measurement_sessions WHERE id = ? AND stage_id = ?",
            (session_id, stage_id)
        )
        if not cursor.fetchone():
            session_id = None

    version_number = generate_version_number(stage_id, db)

    cursor.execute(
        "SELECT content, is_confirmed FROM conclusions WHERE stage_id = ? ORDER BY created_at DESC LIMIT 1",
        (stage_id,)
    )
    concl_row = cursor.fetchone()
    conclusion_snapshot = ""
    if concl_row:
        concl_data = {"content": concl_row["content"], "is_confirmed": concl_row["is_confirmed"]}
        conclusion_snapshot = json.dumps(concl_data, ensure_ascii=False)

    cursor.execute(
        """INSERT INTO measurement_versions 
           (stage_id, version_number, version_name, created_by, modification_description, 
            data_source, parent_version_id, session_id, conclusion_snapshot)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (stage_id, version_number, version_name.strip(), created_by.strip(),
         modification_description.strip(), data_source.strip(),
         parent_version_id, session_id, conclusion_snapshot)
    )
    version_id = cursor.lastrowid

    snapshot_points(version_id, stage_id, db, parent_version_id)
    snapshot_acoustic_data(version_id, stage_id, db, session_id, parent_version_id)
    generate_change_logs(version_id, stage_id, db, parent_version_id, session_id, modification_description)

    db.commit()
    return RedirectResponse(url=f"/stages/{stage_id}/versions/{version_id}", status_code=303)


@router.get("/stages/{stage_id}/versions/compare", response_class=HTMLResponse)
def compare_versions_page(
    request: Request,
    stage_id: int,
    version_a: Optional[int] = Query(None),
    version_b: Optional[int] = Query(None),
    db=Depends(get_db)
):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM stages WHERE id = ?", (stage_id,))
    stage = cursor.fetchone()
    if not stage:
        raise HTTPException(status_code=404, detail="戏台不存在")
    stage = dict(stage)

    cursor.execute("""
        SELECT mv.id, mv.version_number, mv.version_name, mv.created_at, mv.created_by
        FROM measurement_versions mv
        WHERE mv.stage_id = ?
        ORDER BY mv.created_at DESC
    """, (stage_id,))
    versions = [dict(row) for row in cursor.fetchall()]

    result = None
    if version_a and version_b:
        result = compare_two_versions(version_a, version_b, stage_id, db)

    return templates.TemplateResponse("version_compare.html", {
        "request": request, "stage": stage, "versions": versions,
        "version_a": version_a, "version_b": version_b, "result": result
    })


@router.get("/api/stages/{stage_id}/versions/compare-json")
def compare_versions_api(
    stage_id: int,
    version_a: int = Query(...),
    version_b: int = Query(...),
    db=Depends(get_db)
):
    result = compare_two_versions(version_a, version_b, stage_id, db)
    return JSONResponse(content=result)


@router.get("/stages/{stage_id}/versions/{version_id}", response_class=HTMLResponse)
def version_detail(request: Request, stage_id: int, version_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM stages WHERE id = ?", (stage_id,))
    stage = cursor.fetchone()
    if not stage:
        raise HTTPException(status_code=404, detail="戏台不存在")
    stage = dict(stage)

    cursor.execute("""
        SELECT mv.*, pv.version_number as parent_version_number
        FROM measurement_versions mv
        LEFT JOIN measurement_versions pv ON mv.parent_version_id = pv.id
        WHERE mv.id = ? AND mv.stage_id = ?
    """, (version_id, stage_id))
    version = cursor.fetchone()
    if not version:
        raise HTTPException(status_code=404, detail="版本不存在")
    version = dict(version)

    status_map = {
        "pending": "待审核",
        "approved": "已通过",
        "rejected": "已驳回"
    }
    version["review_status_text"] = status_map.get(version["review_status"], version["review_status"])

    cursor.execute(
        "SELECT * FROM version_point_snapshots WHERE version_id = ? ORDER BY label",
        (version_id,)
    )
    point_snapshots = [dict(row) for row in cursor.fetchall()]

    cursor.execute(
        "SELECT * FROM version_acoustic_snapshots WHERE version_id = ? ORDER BY point_label",
        (version_id,)
    )
    acoustic_snapshots = [dict(row) for row in cursor.fetchall()]

    statistics = compute_statistics(acoustic_snapshots)

    cursor.execute(
        "SELECT * FROM version_change_logs WHERE version_id = ? ORDER BY created_at",
        (version_id,)
    )
    change_logs = [dict(row) for row in cursor.fetchall()]

    conclusion_data = None
    if version["conclusion_snapshot"]:
        try:
            conclusion_data = json.loads(version["conclusion_snapshot"])
        except:
            conclusion_data = None

    cursor.execute("""
        SELECT mv.id, mv.version_number, mv.version_name, mv.created_at
        FROM measurement_versions mv
        WHERE mv.stage_id = ? AND mv.id != ?
        ORDER BY mv.created_at DESC
    """, (stage_id, version_id))
    other_versions = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse("version_detail.html", {
        "request": request, "stage": stage, "version": version,
        "point_snapshots": point_snapshots, "acoustic_snapshots": acoustic_snapshots,
        "statistics": statistics, "change_logs": change_logs,
        "conclusion_data": conclusion_data, "other_versions": other_versions
    })


@router.post("/stages/{stage_id}/versions/{version_id}/review")
def review_version(
    stage_id: int,
    version_id: int,
    review_status: str = Form(...),
    reviewed_by: str = Form(""),
    review_comment: str = Form(""),
    db=Depends(get_db)
):
    cursor = db.cursor()
    cursor.execute(
        "SELECT * FROM measurement_versions WHERE id = ? AND stage_id = ?",
        (version_id, stage_id)
    )
    version = cursor.fetchone()
    if not version:
        raise HTTPException(status_code=404, detail="版本不存在")

    if review_status not in ["pending", "approved", "rejected"]:
        raise HTTPException(status_code=400, detail="审核状态无效")

    cursor.execute(
        """UPDATE measurement_versions 
           SET review_status = ?, reviewed_by = ?, review_comment = ?, review_time = CURRENT_TIMESTAMP,
               update_time = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (review_status, reviewed_by.strip(), review_comment.strip(), version_id)
    )
    db.commit()
    return RedirectResponse(url=f"/stages/{stage_id}/versions/{version_id}", status_code=303)


@router.post("/stages/{stage_id}/versions/{version_id}/delete")
def delete_version(stage_id: int, version_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute(
        "SELECT id FROM measurement_versions WHERE id = ? AND stage_id = ?",
        (version_id, stage_id)
    )
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="版本不存在")
    cursor.execute("DELETE FROM measurement_versions WHERE id = ?", (version_id,))
    db.commit()
    return RedirectResponse(url=f"/stages/{stage_id}/versions", status_code=303)
