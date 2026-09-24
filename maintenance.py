import os

MAINT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "maintenance_on.txt")

def is_maintenance_on():
    return os.path.exists(MAINT_FILE)

def turn_on_maintenance():
    with open(MAINT_FILE, "w") as f:
        f.write("Maintenance mode is on.")

def turn_off_maintenance():
    if os.path.exists(MAINT_FILE):
        os.remove(MAINT_FILE)

def set_maintenance(enabled):
    if enabled:
        turn_on_maintenance()
    else:
        turn_off_maintenance()