import sqlite3
import numpy as np 

def get_user_encoding(discord_id, db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT face_encoding FROM users WHERE discord_id=?", (discord_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return np.frombuffer(row[0], dtype=np.float64)
    return None

