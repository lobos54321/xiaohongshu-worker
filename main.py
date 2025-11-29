import asyncio
import os
from typing import Dict, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException, Header
from pydantic import BaseModel
from core.browser import BrowserManager

app = FastAPI(title="XHS Worker Service")

# === CORS Configuration ===
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Configuration ===
WORKER_SECRET = os.getenv("WORKER_SECRET", "default_secret_key")
MAX_CONCURRENT_BROWSERS = asyncio.Semaphore(2)

# === Session Management ===
# Store active login sessions: user_id -> BrowserManager instance
login_sessions: Dict[str, BrowserManager] = {}

class PublishRequest(BaseModel):
    user_id: str
    cookies: str
    video_url: str
    title: str
    desc: str
    proxy_url: Optional[str] = None
    user_agent: Optional[str] = None

class LoginRequest(BaseModel):
    user_id: str
    proxy_url: Optional[str] = None
    user_agent: Optional[str] = None

async def background_publisher(data: PublishRequest):
    """Background task executor"""
    async with MAX_CONCURRENT_BROWSERS:
        print(f"🚦 Task processing started: User {data.user_id}")
        browser = BrowserManager(data.user_id)
        
        loop = asyncio.get_running_loop()
        success, msg = await loop.run_in_executor(
            None, 
            browser.execute_publish,
            data.cookies,
            data.video_url,
            data.title,
            data.desc,
            data.proxy_url,
            data.user_agent
        )
        print(f"🏁 Task finished: User {data.user_id} | Result: {msg}")

@app.post("/api/v1/publish")
async def trigger_publish(
    request: PublishRequest, 
    background_tasks: BackgroundTasks,
    authorization: str = Header(None)
):
    if authorization != f"Bearer {WORKER_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    background_tasks.add_task(background_publisher, request)
    
    return {
        "status": "queued",
        "user_id": request.user_id,
        "message": "Task accepted and queued."
    }

@app.post("/api/v1/login/qrcode")
async def get_login_qrcode(
    request: LoginRequest,
    authorization: str = Header(None)
):
    """
    Start a browser session and get the login QR code
    """
    if authorization != f"Bearer {WORKER_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    # If there's an existing session for this user, close it first
    if request.user_id in login_sessions:
        try:
            login_sessions[request.user_id].close()
        except:
            pass
        del login_sessions[request.user_id]

    # Create new session
    manager = BrowserManager(request.user_id)
    login_sessions[request.user_id] = manager
    
    # Run synchronous browser op in thread pool
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        manager.get_login_qrcode,
        request.proxy_url,
        request.user_agent
    )
    
    if result.get("status") == "error":
        # Cleanup on error
        manager.close()
        del login_sessions[request.user_id]
        raise HTTPException(status_code=500, detail=result.get("msg"))
        
    return result

@app.get("/api/v1/login/status/{user_id}")
async def check_login_status(
    user_id: str,
    authorization: str = Header(None)
):
    """
    Check if the user has scanned the QR code and logged in
    """
    if authorization != f"Bearer {WORKER_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    if user_id not in login_sessions:
        raise HTTPException(status_code=404, detail="Session not found. Please request QR code first.")

    manager = login_sessions[user_id]
    
    loop = asyncio.get_running_loop()
    is_logged_in = await loop.run_in_executor(None, manager.check_login_status)
    
    if is_logged_in:
        # Login successful! 
        # In a real app, you might want to extract cookies here and return them
        # For now, we just return success, and the cookies are persisted in the volume
        
        # Cleanup the browser session as it's no longer needed for interaction
        # But wait! If we close it, we might lose the session if not fully persisted to disk yet?
        # DrissionPage/Chrome usually persists to User Data Dir immediately.
        # Let's keep it open for a moment or close it. 
        # For safety, let's close it to free resources.
        manager.close()
        del login_sessions[user_id]
        
        return {"status": "success", "message": "Login successful"}
    else:
        return {"status": "waiting", "message": "Waiting for scan"}

@app.get("/health")
def health():
    return {"status": "ok"}
