import os
MAINT_FILE = "maintenance_on.txt"

def is_maintenance_on():
    return os.path.exists(MAINT_FILE)

def turn_on_maintenance():
    with open(MAINT_FILE, "w") as f:
        f.write("Maintenance mode is on.")

def turn_off_maintenance():
    if os.path.exists(MAINT_FILE):
        os.remove(MAINT_FILE)