import time
from collections import deque
from typing import List, Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import csv
import os
from datetime import datetime
import sqlite3

DB_FILE = "example_dogs.db"

DOG_HR_LIMITS = {
    "small": {"min": 70, "max": 120},
    "medium": {"min": 60, "max": 100},
    "large": {"min": 50, "max": 90}
}

# ===== DB 초기화 =====
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # 강아지 등록 테이블
    c.execute("""
    CREATE TABLE IF NOT EXISTS dogs (
        dog_id TEXT PRIMARY KEY,
        size TEXT
    )
    """)
    # BPM 데이터 테이블
    c.execute("""
    CREATE TABLE IF NOT EXISTS bpm_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dog_id TEXT,
        bpm INTEGER,
        status TEXT,
        timestamp DATETIME
    )
    """)
    conn.commit()
    conn.close()

init_db()

# 현재 활성화된 강아지 ID (프론트에서 선택)
active_dog_id: Optional[str] = None

# ===== 메모리 저장 =====
dog_sizes = {}
def load_dog_sizes():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT dog_id, size FROM dogs")
    for dog_id, size in c.fetchall():
        dog_sizes[dog_id] = size
    conn.close()
load_dog_sizes()

# ===== FastAPI 앱 생성 =====
app = FastAPI(title="BPM Stream API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5500"],  # 프론트엔드 실제 주소
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== 데이터 버퍼 =====
BUFFER_SIZE = 10_000
data_buffer: deque = deque(maxlen=BUFFER_SIZE)

CSV_FILE = "hr_data.csv"
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "dog_id",  "bpm", "status"])

# ===== 모델 정의 =====
class HeartbeatIn(BaseModel):
    device_id: Optional[str] = None
    bpm: float

class Sample(BaseModel):
    ts: float
    bpm: int
    status: str

class SamplesResponse(BaseModel):
    count: int
    samples: List[Sample]

class DogRegister(BaseModel):
    dog_id: str
    size: str  # small/medium/large

# ===== 라우트 정의 =====
@app.get("/")
def root():
    return {"ok": True, "message": "BPM Stream API running."}

@app.post("/activate_dog")
async def activate_dog(payload: DogRegister):
    global active_dog_id
    active_dog_id = payload.dog_id
# dog_sizes 메모리 업데이트
    dog_sizes[payload.dog_id] = payload.size

    # DB에 등록 (없으면 새로, 있으면 업데이트)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO dogs (dog_id, size) VALUES (?, ?)",
        (payload.dog_id, payload.size)
    )
    conn.commit()
    conn.close()

    print("🚀 Received data:", {"dog_id": payload.dog_id, "size": payload.size})
    print("💡 Debug Info:", {"dog_id": payload.dog_id, "size": payload.size, "limits": DOG_HR_LIMITS[payload.size]})

    return {"ok": True, "active_dog": active_dog_id, "size": payload.size}

@app.post("/register_dog")
async def register_dog(payload: DogRegister):
    dog_sizes[payload.dog_id] = payload.size
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO dogs (dog_id, size) VALUES (?, ?)",
              (payload.dog_id, payload.size))
    conn.commit()
    conn.close()
    return {"ok": True, "dog_id": payload.dog_id, "size": payload.size}

@app.post("/heartbeat_raw")
async def post_heartbeat_raw(payload: HeartbeatIn):
    global active_dog_id
    if not active_dog_id:
        return {"ok": False, "error": "No active dog_id set"}
    
    dog_id = active_dog_id
    bpm = int(round(payload.bpm))
    ts = time.time()

    # 이전 bpm 가져오기
    previous_bpm = data_buffer[-1]["bpm"] if data_buffer else bpm

    # 범위 체크
    if bpm < 30 or bpm > 220:
        bpm = previous_bpm
    if abs(bpm - previous_bpm) > 20:
        bpm = previous_bpm


    size = dog_sizes.get(dog_id, "medium")
    limits = DOG_HR_LIMITS[size]

    print("💡 Debug Info:", {
        "dog_id": dog_id,
        "size": size,
        "limits": limits,
        "bpm": bpm
    })

    status = "low" if bpm < limits["min"] else "high" if bpm > limits["max"] else "normal"

    item = {"ts": ts, "bpm": bpm, "status": status, "dog_id": dog_id}
    data_buffer.append(item)

    # CSV 기록
    with open(CSV_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
                         dog_id, bpm, status])

    # DB 기록
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO bpm_data (dog_id, bpm, status, timestamp) VALUES (?, ?, ?, ?)",
        (dog_id, bpm, status, datetime.fromtimestamp(ts))
    )
    conn.commit()
    conn.close()

    return {"ok": True, "stored": item}


@app.get("/latest", response_model=Sample)
def get_latest():
    if not data_buffer:
        return Sample(ts=0.0, bpm=0, status="none")
    return Sample(**data_buffer[-1])

@app.get("/data", response_model=SamplesResponse)
def get_data(n: int = 100):
    items = list(data_buffer)[-n:]
    return SamplesResponse(count=len(items), samples=[Sample(**x) for x in items])

from datetime import datetime, timedelta

@app.get("/report/weekly")
def get_weekly_report(dog_id: Optional[str] = None):
    """최근 7일간 BPM 요약"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    query = """
        SELECT 
            strftime('%Y-%m-%d', timestamp) AS date,
            AVG(bpm) AS avg_bpm,
            MAX(bpm) AS max_bpm,
            MIN(bpm) AS min_bpm,
            SUM(CASE WHEN status='high' THEN 1 ELSE 0 END) AS high_count,
            SUM(CASE WHEN status='low' THEN 1 ELSE 0 END) AS low_count,
            SUM(CASE WHEN status='normal' THEN 1 ELSE 0 END) AS normal_count
        FROM bpm_data
        WHERE timestamp >= datetime('now', '-7 days')
        {dog_filter}
        GROUP BY date
        ORDER BY date;
    """.format(dog_filter=f"AND dog_id='{dog_id}'" if dog_id else "")

    c.execute(query)
    rows = c.fetchall()
    conn.close()

    report = []
    for row in rows:
        report.append({
            "date": row[0],
            "avg_bpm": row[1],
            "max_bpm": row[2],
            "min_bpm": row[3],
            "high_count": row[4],
            "low_count": row[5],
            "normal_count": row[6]
        })

    return {"period": "weekly", "days": len(report), "report": report}


@app.get("/report/monthly")
def get_monthly_report(dog_id: Optional[str] = None):
    """최근 30일간 BPM 요약"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    query = """
        SELECT 
            strftime('%Y-%m-%d', timestamp) AS date,
            AVG(bpm) AS avg_bpm,
            MAX(bpm) AS max_bpm,
            MIN(bpm) AS min_bpm
        FROM bpm_data
        WHERE timestamp >= datetime('now', '-30 days')
        {dog_filter}
        GROUP BY date
        ORDER BY date;
    """.format(dog_filter=f"AND dog_id='{dog_id}'" if dog_id else "")

    c.execute(query)
    rows = c.fetchall()
    conn.close()

    report = []
    for row in rows:
        report.append({
            "date": row[0],
            "avg_bpm": row[1],
            "max_bpm": row[2],
            "min_bpm": row[3]
        })

    return {"period": "monthly", "days": len(report), "report": report}
