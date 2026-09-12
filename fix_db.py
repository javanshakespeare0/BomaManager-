import sqlite3

conn = sqlite3.connect('instance/site.db') # CHANGE if your db name is different
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE user ADD COLUMN is_landlord BOOLEAN DEFAULT 0")
    print("Added is_landlord")
except Exception as e:
    print(e)

try:
    cursor.execute("ALTER TABLE user ADD COLUMN subscription_status VARCHAR(20) DEFAULT 'trial'")
    print("Added subscription_status")
except Exception as e:
    print(e)

try:
    cursor.execute("ALTER TABLE user ADD COLUMN subscription_plan VARCHAR(20) DEFAULT 'basic'")
    print("Added subscription_plan")
except Exception as e:
    print(e)

try:
    cursor.execute("ALTER TABLE user ADD COLUMN subscription_expiry DATETIME")
    print("Added subscription_expiry")
except Exception as e:
    print(e)

try:
    cursor.execute("ALTER TABLE user ADD COLUMN trial_ends_at DATETIME")
    print("Added trial_ends_at")
except Exception as e:
    print(e)
conn.commit()
conn.close()
print("DONE - Now run python app.py")