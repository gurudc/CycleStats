"""Daily coach note script for LXC cron."""
import sys, os, re, subprocess, json

# Read env
with open("/etc/systemd/system/cyclestats.service.d/env.conf") as f:
    for line in f:
        m = re.match(r"Environment=DATABASE_URL=(.+)", line)
        if m:
            os.environ["DATABASE_URL"] = m.group(1).strip()
        if "DEEPSEEK" in line:
            os.environ["DEEPSEEK_API_KEY"] = line.strip().split("=")[-1]

sys.path.insert(0, "/opt/cyclestats/backend")
from database import SessionLocal, Activity, CoachNote
from datetime import date, timedelta
import requests

db = SessionLocal()
try:
    today = date.today()
    sda = (today - timedelta(days=14)).isoformat()
    
    # Collect training data
    recent = db.query(Activity).filter(
        Activity.start_time >= sda,
        Activity.tss.isnot(None)
    ).order_by(Activity.start_time.desc()).limit(10).all()
    
    rl = []
    for a in recent:
        rl.append({
            "name": a.name, "date": str(a.start_time)[:10] if a.start_time else None,
            "tss": a.tss, "duration_h": round((a.moving_time_s or 0)/3600, 1),
            "distance_km": round((a.distance_m or 0)/1000, 1),
        })
    
    data = {
        "athlete_name": "David", "date": today.isoformat(),
        "current_ftp_w": 236, "ride_count_14d": len(rl),
        "recent_activities": rl[:8],
    }
    
    prev = db.query(CoachNote).order_by(CoachNote.id.desc()).first()
    if prev:
        data["previous_note"] = prev.note
    
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("No API key")
        sys.exit(1)
    
    resp = requests.post("https://api.deepseek.com/chat/completions",
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "You are an experienced cycling coach. Write a concise 3-5 sentence daily coaching note. Address the athlete by name. Reference specific numbers. Give one actionable recommendation. Plain text only."},
                {"role": "user", "content": json.dumps(data)}
            ],
            "max_tokens": 500
        },
        timeout=30)
    
    if resp.status_code == 200:
        note = resp.json()["choices"][0]["message"]["content"].strip()
        cn = CoachNote(note=note, date=today.isoformat(), prompt_data=None)
        db.add(cn)
        db.commit()
        print("Coach note saved:", note[:80])
    else:
        print(f"API error: {resp.status_code}")
finally:
    db.close()
