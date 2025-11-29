import asyncio
import os
from typing import Dict, Optional, List, Union
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
    cookies: Union[str, List[Dict]]
    publish_type: str = "video" # "video" or "image"
    video_url: Optional[str] = None
    files: Optional[List[str]] = [] # List of URLs (video or images)
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
        print(f"🚦 Task processing started: User {data.user_id} | Type: {data.publish_type}")
        browser = BrowserManager(data.user_id)
        
        # Prepare file list
        urls_to_download = []
        if data.files:
            urls_to_download = data.files
        elif data.video_url:
            urls_to_download = [data.video_url]
            
        # Download all files
        from core.utils import download_file
        local_files = []
        try:
            for url in urls_to_download:
                suffix = ".mp4" if data.publish_type == "video" else ".jpg"
                # Simple heuristic for extension
                if ".png" in url.lower(): suffix = ".png"
                if ".jpg" in url.lower() or ".jpeg" in url.lower(): suffix = ".jpg"
                
                print(f"📥 Downloading file: {url}")
                path = download_file(url, suffix=suffix)
                print(f"✅ Download complete: {path}")
                local_files.append(path)
                
            loop = asyncio.get_running_loop()
            success, msg = await loop.run_in_executor(
                None, 
                browser.publish_content,
                data.cookies,
                data.publish_type,
                local_files,
                data.title,
                data.desc,
                data.proxy_url,
                data.user_agent
            )
            print(f"🏁 Task finished: User {data.user_id} | Result: {msg}")
        except Exception as e:
            print(f"❌ Task failed: {e}")
            # Cleanup if failed before browser cleanup
            for f in local_files:
                if os.path.exists(f):
                    try: os.remove(f)
                    except: pass

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
    
    # Run synchronous browser op in thread pool with timeout
    loop = asyncio.get_running_loop()
    try:
        print(f"[{request.user_id}] 🚀 Requesting QR code...")
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                manager.get_login_qrcode,
                request.proxy_url,
                request.user_agent
            ),
            timeout=45.0
        )
        print(f"[{request.user_id}] ✅ QR code request completed: {result.get('status')}")
    except asyncio.TimeoutError:
        print(f"[{request.user_id}] ❌ QR code request timed out")
        manager.close()
        del login_sessions[request.user_id]
        raise HTTPException(status_code=504, detail="Browser initialization timed out")
    except Exception as e:
        print(f"[{request.user_id}] ❌ QR code request failed: {e}")
        manager.close()
        del login_sessions[request.user_id]
        raise HTTPException(status_code=500, detail=str(e))
    
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
        # Get cookies before closing the browser
        cookies = await loop.run_in_executor(None, manager.get_cookies)
        
        # Cleanup the browser session as it's no longer needed for interaction
        manager.close()
        del login_sessions[user_id]
        
        if cookies:
            return {
                "status": "success", 
                "message": "Login successful",
                "cookies": cookies
            }
        else:
            # Login successful but cookies could not be extracted
            return {
                "status": "success", 
                "message": "Login successful, but failed to extract cookies"
            }
    else:
        return {"status": "waiting", "message": "Waiting for scan"}

@app.delete("/api/v1/login/session/{user_id}")
async def close_session(
    user_id: str,
    authorization: str = Header(None)
):
    """
    Close the browser session and clean up user data
    """
    if authorization != f"Bearer {WORKER_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Close active session if exists
    if user_id in login_sessions:
        try:
            login_sessions[user_id].close()
        except:
            pass
        del login_sessions[user_id]

    # Clean up user data directory
    # Note: BrowserManager.close() doesn't delete the dir, so we do it here manually if needed
    # But since we want to support persistent sessions, maybe we SHOULDN'T delete it?
    # User asked "Will it be cleared?". If they click Logout, they expect it to be cleared.
    # So yes, we should delete it here.
    
    user_data_dir = os.path.abspath(os.path.join("data", "users", user_id))
    if os.path.exists(user_data_dir):
        import shutil
        try:
            shutil.rmtree(user_data_dir)
        except Exception as e:
            print(f"Error cleaning up user data: {e}")

    return {"status": "success", "message": "Session closed and data cleaned"}

@app.get("/health")
def health():
    return {"status": "ok"}
