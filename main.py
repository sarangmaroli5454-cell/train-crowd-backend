import os
from typing import List

import redis
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Train Crowd Backend")

# Local testing uses localhost; on Render set REDIS_URL to your Redis URL.
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
r = redis.from_url(REDIS_URL, decode_responses=True)

CROWD_MULTIPLIER = 1.25   # a guess for now - calibrate in the field trial
SEAT_CAPACITY = 300       # 3 general coaches combined
WINDOW_SECONDS = 90


class TelemetryBatch(BaseModel):
    train_number: str
    timestamp: int
    hashes: List[str]


@app.get("/")
def home():
    return {"message": "Server is up and running!"}


@app.post("/api/v1/telemetry/report")
def receive_signals(payload: TelemetryBatch):
    if not payload.hashes:
        return {"status": "ignored", "reason": "no hashes"}

    window_id = payload.timestamp // WINDOW_SECONDS
    window_key = f"train:{payload.train_number}:win:{window_id}"

    r.sadd(window_key, *payload.hashes)  # a set removes duplicates
    r.expire(window_key, 900)
    r.set(f"train:{payload.train_number}:latest_win", window_id, ex=900)

    return {"status": "saved", "count_received": len(payload.hashes)}


@app.get("/api/v1/train/{train_number}/crowd")
def check_crowd(train_number: str):
    latest_win = r.get(f"train:{train_number}:latest_win")
    if not latest_win:
        return {"status": "NO_DATA", "message": "No scans available recently"}

    unique_devices = r.scard(f"train:{train_number}:win:{latest_win}")
    estimated_people = int(unique_devices * CROWD_MULTIPLIER)
    occupancy_pct = int((estimated_people / SEAT_CAPACITY) * 100)

    if occupancy_pct < 70:
        status = "SEATS_AVAILABLE (Green)"
    elif occupancy_pct <= 115:
        status = "STANDING_ROOM (Yellow)"
    else:
        status = "HEAVY_RUSH (Red)"

    return {
        "train_number": train_number,
        "unique_devices": unique_devices,
        "estimated_people": estimated_people,
        "occupancy_pct": occupancy_pct,
        "status": status,
    }
