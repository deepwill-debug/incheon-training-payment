import schedule
import time
import subprocess
import os
from datetime import datetime

def run_update():
    print(f"[{datetime.now()}] Starting scheduled update...")
    try:
        # Run the update script
        # Using sys.executable ensures we use the same python environment
        import sys
        result = subprocess.run([sys.executable, 'bot_update_courses.py'], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"[{datetime.now()}] Update successful:")
            print(result.stdout)
        else:
            print(f"[{datetime.now()}] Update failed:")
            print(result.stderr)
    except Exception as e:
        print(f"[{datetime.now()}] Error running update: {e}")

# Schedule for 08:00 AM every day
schedule.every().day.at("08:00").do(run_update)

print(f"[{datetime.now()}] Scheduler started. Waiting for 08:00 AM...")

# Initial run to make sure data is fresh
run_update()

while True:
    schedule.run_pending()
    time.sleep(60) # Check every minute
