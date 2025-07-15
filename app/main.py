from fastapi import FastAPI, File, UploadFile, Form, HTTPException 
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import sqlite3
import face_recognition
from io import BytesIO
import httpx
import os
from dotenv import load_dotenv 
from jose import jwt, JWTError
from utils import get_user_encoding 

load_dotenv()

app = FastAPI()
app.mount("/static", StaticFiles(directory="app/static"), name="static")

DB_PATH = "users.db"
JWT_SECRET = os.getenv("JWTSECRET") 
JWT_ALGORITHM = "HS256"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            discord_id TEXT PRIMARY KEY,
            face_encoding BLOB,
            servers TEXT
        )
    """)
    conn.commit()
    conn.close()


init_db()


def save_user_encoding(discord_id, encoding, server_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    blob = encoding.tobytes()

    # Update server list if exists
    c.execute("SELECT servers FROM users WHERE discord_id=?", (discord_id,))
    row = c.fetchone()
    if row:
        existing = set(row[0].split(","))
        existing.add(server_id)
        server_list = ",".join(existing)
    else:
        server_list = server_id

    c.execute(
        "INSERT OR REPLACE INTO users (discord_id, face_encoding, servers) VALUES (?, ?, ?)",
        (discord_id, blob, server_list),
    )
    conn.commit()
    conn.close()


def create_token(discord_id: str, server_id: str, server_name: str):
    return jwt.encode({"discord_id": discord_id, "server_id": server_id, "server_name": server_name}, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None


@app.get("/verify/{token}/{server_id}", response_class=HTMLResponse)
async def verify_page(token: str, server_id: str):
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=403, detail="Invalid or tampered token")

    if server_id != payload.get("server_id"):
        raise HTTPException(status_code=403, detail="Server ID mismatch")

    discord_id = payload.get("discord_id")
    server_name = payload.get("server_name")

    encoding = get_user_encoding(discord_id, DB_PATH)
    mode = "register" if encoding is None else "verify"

    html_file = "app/templates/register.html" if mode == "register" else "app/templates/verify.html"

    with open(html_file) as f:
        html = f.read()

    html = html.replace("{{discord_id}}", str(discord_id))
    html = html.replace("{{server_id}}", str(server_id))
    html = html.replace("{{server_name}}", str(server_name))
    html = html.replace("{{token}}", token)  
    return html

@app.post("/register")
async def register_user(file: UploadFile = File(...), discord_id: str = Form(...), server_id: str = Form(...)):
    contents = await file.read()
    image = face_recognition.load_image_file(BytesIO(contents))
    encodings = face_recognition.face_encodings(image)
    if not encodings:
        return {"status": "fail", "message": "No face detected in the image."}
    save_user_encoding(discord_id, encodings[0], server_id)
    return {"status": "success", "message": "✅ Face registered successfully."}


@app.post("/verify")
async def verify_user(
    file: UploadFile = File(...),
    discord_id: str = Form(...),
    server_id: str = Form(...),
    server_name: str = Form(...),
    token: str = Form(...)
):
    payload = decode_token(token)
    if payload is None:
        return {"status": "fail", "message": "Invalid or tampered token."}

    if discord_id != payload.get("discord_id"):
        return {"status": "fail", "message": "Discord ID mismatch."}
    if server_id != payload.get("server_id"):
        return {"status": "fail", "message": "Server ID mismatch."}
    if server_name != payload.get("server_name"):
        return {"status": "fail", "message": "Server name mismatch."}

    user_encoding = get_user_encoding(discord_id, DB_PATH)
    if user_encoding is None:
        return {"status": "fail", "message": "User not registered yet."}

    contents = await file.read()
    unknown_image = face_recognition.load_image_file(BytesIO(contents))
    unknown_encodings = face_recognition.face_encodings(unknown_image)
    if not unknown_encodings:
        return {"status": "fail", "message": "No face detected in the image."}

    results = face_recognition.compare_faces([user_encoding], unknown_encodings[0])
    if results[0]:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    "http://localhost:5000/verified",
                    json={"discord_id": discord_id, "server_id": server_id}
                )
                if r.status_code != 200:
                    return {"status": "partial", "message": "Verified, but failed to notify bot."}
        except Exception as e:
            print(f"Error notifying bot: {e}")
            return {"status": "partial", "message": "Verified, but error notifying bot."}

        return {"status": "success", "message": "Face verified! ✅"}
    else:
        return {"status": "fail", "message": "Face did not match. ❌"}
