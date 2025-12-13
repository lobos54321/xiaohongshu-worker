import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from datetime import datetime
from typing import Dict, Optional, List, Union
from fastapi import FastAPI, BackgroundTasks, HTTPException, Header, WebSocket, WebSocketDisconnect, Body, Response
from pydantic import BaseModel
from core.browser import BrowserManager
from core.utils import clean_all_user_data
from core.ai_agent import AutoContentManager

from fastapi.staticfiles import StaticFiles

app = FastAPI(title="XHS Worker Service")

# Ensure image directory exists
os.makedirs("data/images", exist_ok=True)
app.mount("/images", StaticFiles(directory="data/images"), name="images")

# === CORS Configuration ===
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://prome.live",
        "https://www.prome.live",
        "http://localhost:5173",
        "http://localhost:3000",
        "https://xiaohongshu-automation-ai.zeabur.app"
    ],
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

# Initialize AI Agent Manager
auto_content_manager = AutoContentManager()

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
    force_fresh: bool = False  # Force fresh login, clean all old user data

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

class CookieSyncRequest(BaseModel):
    user_id: str
    cookies: List[dict]
    ua: str

@app.post("/api/v1/login/sync")
async def api_sync_cookie(
    req: CookieSyncRequest,
    authorization: str = Header(None)
):
    """
    Receive cookies from Chrome Extension and save them.
    NOTE: Browser verification removed to avoid crashes in container environments.
    The cookies will be validated when actually used (e.g., for publishing or profile fetch).
    """
    if authorization != f"Bearer {WORKER_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Ensure user directory exists
    user_dir = os.path.abspath(f"data/users/{req.user_id}")
    os.makedirs(user_dir, exist_ok=True)
    
    # Save UA
    with open(f"{user_dir}/ua.txt", "w") as f:
        f.write(req.ua)
        
    # Save Cookies
    import json
    cookie_path = f"{user_dir}/cookies.json"
    with open(cookie_path, "w") as f:
        json.dump(req.cookies, f)
    
    print(f"[{req.user_id}] ✅ Cookies saved successfully ({len(req.cookies)} cookies)")
    
    return {
        "status": "success", 
        "message": f"Cookies saved successfully ({len(req.cookies)} cookies)",
        "user_id": req.user_id,
        "cookie_count": len(req.cookies)
    }


# 前端专用的 Cookie 同步端点（不需要 Bearer token，由 CORS 保护）
@app.post("/api/v1/login/sync-web")
async def api_sync_cookie_web(
    req: CookieSyncRequest
):
    """
    Receive cookies from Web Frontend (prome.live)
    Protected by CORS - only allowed origins can call this
    Cookies from the extension are trusted and saved directly without browser verification
    """
    print(f"[{req.user_id}] 📥 Received cookies from web frontend, count={len(req.cookies)}")
    
    # Check for essential cookies
    cookie_names = [c.get('name', '') for c in req.cookies]
    has_web_session = 'web_session' in cookie_names
    has_a1 = 'a1' in cookie_names
    
    print(f"[{req.user_id}] 🔍 Cookie check: web_session={has_web_session}, a1={has_a1}")
    
    if not has_a1:
        return {"success": False, "status": "error", "message": "Missing essential cookie (a1). Please ensure you are logged in to Xiaohongshu."}
    
    # Ensure user directory exists
    user_dir = os.path.abspath(f"data/users/{req.user_id}")
    os.makedirs(user_dir, exist_ok=True)
    
    # Save UA
    with open(f"{user_dir}/ua.txt", "w") as f:
        f.write(req.ua)
        
    # Save Cookies
    import json
    cookie_path = f"{user_dir}/cookies.json"
    with open(cookie_path, "w") as f:
        json.dump(req.cookies, f)
    
    print(f"[{req.user_id}] ✅ Cookies saved successfully (skipping browser verification - trusted source)")
    
    return {
        "success": True, 
        "status": "success", 
        "message": "Cookies synced successfully",
        "has_web_session": has_web_session,
        "cookie_count": len(req.cookies)
    }



@app.post("/api/v1/login/sync-complete")
async def sync_complete_cookies(
    user_id: str = Body(...),
    cookies: List[Dict] = Body(...),
    ua: str = Body(...),
    authorization: str = Header(None)
):
    """
    接收本地登录工具上传的完整Cookie（包括HttpOnly）
    用于全自动运营模式
    """
    if authorization != f"Bearer {WORKER_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    print(f"[{user_id}] 📥 Receiving complete cookies from local tool")
    print(f"[{user_id}] 🍪 Cookie count: {len(cookies)}")
    
    # Create user directory
    user_dir = os.path.abspath(f"data/users/{user_id}")
    os.makedirs(user_dir, exist_ok=True)
    
    # Save User-Agent
    ua_path = f"{user_dir}/ua.txt"
    with open(ua_path, "w") as f:
        f.write(ua)
    
    # Save cookies with metadata
    cookie_data = {
        "source": "local_tool",
        "synced_at": time.time(),
        "cookies": cookies
    }
    
    cookie_path = f"{user_dir}/cookies.json"
    with open(cookie_path, "w") as f:
        json.dump(cookie_data, f, indent=2)
    
    print(f"[{user_id}] ✅ Complete cookies saved successfully")
    print(f"[{user_id}] 📝 Cookie names: {[c['name'] for c in cookies[:10]]}")
    
    return {
        "status": "success",
        "message": "Complete cookies synced successfully. You can now use full-auto mode.",
        "cookie_count": len(cookies),
        "source": "local_tool"
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

    # If force_fresh=True, clean all user data directories
    if request.force_fresh:
        users_base_dir = os.path.abspath("data/users")
        clean_all_user_data(users_base_dir, request.user_id)

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
    try:
        print(f"[{request.user_id}] 🚀 Requesting QR code...")
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                manager.get_login_qrcode,
                request.proxy_url,
                request.user_agent
            ),
            timeout=90.0
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


# 前端专用的登录状态检查端点（检查已保存的 Cookie）
@app.get("/api/v1/login/check-web/{user_id}")
async def check_login_status_web(user_id: str):
    """
    Check if user is logged in using saved cookies
    Protected by CORS - only allowed origins can call this
    """
    import json
    
    user_dir = os.path.abspath(f"data/users/{user_id}")
    cookie_path = f"{user_dir}/cookies.json"
    
    # Check if cookies exist
    if not os.path.exists(cookie_path):
        print(f"[{user_id}] ❌ No cookies found")
        return {"status": "not_logged_in", "is_logged_in": False, "message": "No cookies found"}
    
    try:
        # Load cookies
        with open(cookie_path, "r") as f:
            cookies = json.load(f)
        
        if not cookies or len(cookies) == 0:
            return {"status": "not_logged_in", "is_logged_in": False, "message": "No cookies found"}
        
        # Check for essential cookies that indicate login
        essential_cookies = ['web_session', 'galaxy_creator_session_id', 'a1']
        has_essential = any(
            cookie.get('name') in essential_cookies 
            for cookie in cookies
        )
        
        if has_essential:
            print(f"[{user_id}] ✅ Found essential cookies, user is logged in")
            return {"status": "logged_in", "is_logged_in": True, "message": "User is logged in"}
        else:
            print(f"[{user_id}] ⚠️ Cookies exist but no essential login cookies found")
            return {"status": "not_logged_in", "is_logged_in": False, "message": "No essential login cookies"}
            
    except Exception as e:
        print(f"[{user_id}] ❌ Error checking cookies: {e}")
        return {"status": "error", "is_logged_in": False, "message": str(e)}

@app.delete("/api/v1/login/session/{user_id}")
async def close_session(
    user_id: str,
    authorization: str = Header(None)
):
    """
    Close the browser session and clean up ALL user data
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

    # Clean up ALL user data directories to ensure no session leakage
    users_base_dir = os.path.abspath("data/users")
    clean_all_user_data(users_base_dir, user_id)

    return {"status": "success", "message": "Session closed and ALL user data cleaned"}

@app.get("/health")
def health():
    return {"status": "ok"}

# === Configuration Endpoints ===

@app.get("/api/v1/config/supabase")
async def get_supabase_config(
    response: Response
):
    """
    Return Supabase configuration for Chrome extension
    This allows the extension to sync analytics data to Supabase
    Public endpoint - no auth required (anon key is safe to expose)
    """
    # Add CORS headers
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_ANON_KEY")
    
    if not supabase_url or not supabase_key:
        raise HTTPException(
            status_code=500, 
            detail="Supabase configuration not found in environment variables"
        )
    
    return {
        "success": True,
        "config": {
            "url": supabase_url,
            "key": supabase_key
        }
    }

class AnalyticsSyncRequest(BaseModel):
    userId: str
    publishedNotes: List[Dict] = []
    analyticsData: List[Dict] = []

@app.post("/api/v1/analytics/sync")
async def sync_analytics(
    request: AnalyticsSyncRequest,
    response: Response
):
    """
    Sync analytics data from extension to Supabase via backend
    This serves as a fallback when extension cannot connect to Supabase directly
    """
    # Add CORS headers
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    
    try:
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_ANON_KEY")
        
        if not supabase_url or not supabase_key:
            raise HTTPException(status_code=500, detail="Supabase not configured on backend")
            
        # Use requests library (no need for supabase client)
        import requests as req
        headers = {
            'Content-Type': 'application/json',
            'apikey': supabase_key,
            'Authorization': f'Bearer {supabase_key}'
        }
        
        notes_count = 0
        analytics_count = 0
        
        # 1. Sync published notes
        if request.publishedNotes:
            notes_data = [
                {**note, 'user_id': request.userId}
                for note in request.publishedNotes
            ]
            
            try:
                # Direct HTTP POST to Supabase REST API
                r = req.post(
                    f"{supabase_url}/rest/v1/xhs_published_notes",
                    json=notes_data,
                    headers={**headers, 'Prefer': 'return=representation'}
                )
                if r.ok:
                    notes_count = len(r.json())
                    print(f"Saved {notes_count} notes")
            except Exception as e:
                print(f"Error syncing notes: {e}")

        # 2. Sync analytics data
        if request.analyticsData:
            analytics_data = [
                {**item, 'user_id': request.userId}
                for item in request.analyticsData
            ]
            
            try:
                r = req.post(
                    f"{supabase_url}/rest/v1/xhs_note_analytics",
                    json=analytics_data,
                    headers={**headers, 'Prefer': 'return=representation'}
                )
                if r.ok:
                    analytics_count = len(r.json())
                    print(f"Saved {analytics_count} analytics records")
                else:
                    print(f"Analytics save error: {r.text}")
                    raise HTTPException(status_code=500, detail=r.text)
            except Exception as e:
                print(f"Error syncing analytics: {e}")
                raise

        return {
            "success": True,
            "notesCount": notes_count,
            "analyticsCount": analytics_count
        }
        
    except Exception as e:
        print(f"Analytics sync failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# === AI Agent Endpoints ===

class AutoStartRequest(BaseModel):
    userId: str
    productName: str
    targetAudience: str = "Target Audience"
    marketingGoal: str = "brand"
    postFrequency: str = "daily"
    brandStyle: str = "warm"
    reviewMode: str = "auto"

@app.post("/agent/auto/start")
async def start_auto_mode(
    request: AutoStartRequest,
    authorization: str = Header(None)
):
    if authorization != f"Bearer {WORKER_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    await auto_content_manager.start_auto_mode(request.dict())
    
    return {
        "success": True,
        "message": f"Auto mode started for {request.productName}",
        "data": {
            "userId": request.userId,
            "status": "generating",
            "startTime": datetime.now().isoformat()
        }
    }

@app.get("/agent/auto/status/{user_id}")
async def get_auto_status(
    user_id: str,
    authorization: str = Header(None)
):
    if authorization != f"Bearer {WORKER_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    status = auto_content_manager.get_status(user_id)
    return {"status": status}

@app.get("/agent/auto/strategy/{user_id}")
async def get_auto_strategy(
    user_id: str,
    authorization: str = Header(None)
):
    if authorization != f"Bearer {WORKER_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    strategy = auto_content_manager.get_strategy(user_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
        
    return {"success": True, "strategy": strategy}

@app.get("/agent/auto/plan/{user_id}")
async def get_auto_plan(
    user_id: str,
    authorization: str = Header(None)
):
    if authorization != f"Bearer {WORKER_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    tasks = auto_content_manager.get_daily_tasks(user_id)
    
    # Format for frontend
    formatted_tasks = []
    for i, task in enumerate(tasks):
        formatted_tasks.append({
            "id": str(i + 1),
            "title": task["title"],
            "scheduledTime": task["scheduledTime"],
            "status": task["status"],
            "type": task["contentType"],
            "content": task["content"],
            "image_urls": task["imageUrls"],
            "hashtags": task["hashtags"]
        })
        
    return {
        "success": True, 
        "plan": {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "tasks": formatted_tasks
        }
    }

class ApproveRequest(BaseModel):
    taskId: str

@app.post("/agent/auto/approve/{user_id}")
async def approve_task(
    user_id: str,
    request: ApproveRequest,
    background_tasks: BackgroundTasks,
    authorization: str = Header(None)
):
    if authorization != f"Bearer {WORKER_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Find the task
    tasks = auto_content_manager.get_daily_tasks(user_id)
    task_to_publish = None
    
    # Simple matching by title or ID (assuming ID is index+1)
    try:
        idx = int(request.taskId) - 1
        if 0 <= idx < len(tasks):
            task_to_publish = tasks[idx]
    except:
        pass
        
    if not task_to_publish:
        # Try matching by title
        for task in tasks:
            if task["title"] == request.taskId:
                task_to_publish = task
                break
    
    if not task_to_publish:
        raise HTTPException(status_code=404, detail="Task not found")

    # Trigger publishing
    # We need cookies for this user. 
    # In a real scenario, we should load them from the user's session file.
    # For now, we'll assume the user is logged in and we can get cookies from the file system.
    
    user_dir = os.path.abspath(f"data/users/{user_id}")
    cookie_path = f"{user_dir}/cookies.json"
    
    if not os.path.exists(cookie_path):
        raise HTTPException(status_code=400, detail="User not logged in. Please login first.")
        
    with open(cookie_path, 'r') as f:
        cookies = json.load(f)
        
    # Reuse the existing background_publisher logic
    publish_req = PublishRequest(
        user_id=user_id,
        cookies=cookies,
        publish_type="image", # AI generated content is usually images
        files=task_to_publish["imageUrls"],
        title=task_to_publish["title"],
        desc=task_to_publish["content"] + "\n\n" + " ".join(task_to_publish["hashtags"])
    )
    
    background_tasks.add_task(background_publisher, publish_req)
    
    return {
        "success": True,
        "message": "Task approved and queued for publishing",
        "jobId": f"job-{int(datetime.now().timestamp())}"
    }



# ==================== Account Sync Endpoints ====================

@app.get("/agent/xiaohongshu/profile")
async def get_xhs_profile_and_sync(
    userId: str,
    authorization: str = Header(None)
):
    """
    Get user profile from XHS and sync to Supabase
    This is called by the frontend after login to register the account
    """
    # 1. Load Cookies
    user_dir = os.path.abspath(f"data/users/{userId}")
    cookie_path = f"{user_dir}/cookies.json"
    
    if not os.path.exists(cookie_path):
        raise HTTPException(status_code=401, detail="No cookies found. Please login first.")
        
    try:
        import json
        with open(cookie_path, "r") as f:
            cookies = json.load(f)
    except:
        raise HTTPException(status_code=401, detail="Invalid cookie file.")
        
    # 2. Extract web_session for hash
    web_session = next((c['value'] for c in cookies if c['name'] == 'web_session'), None)
    if not web_session:
        print(f"[{userId}] ⚠️ Sync failed: No web_session found")
        # Proceed anyway? No, web_session is critical for identity
        # raise HTTPException(status_code=400, detail="No web_session cookie found")
        
    # 3. Call XHS API
    import requests
    
    # Format cookies for requests
    cookie_dict = {c['name']: c['value'] for c in cookies}
    
    # Load UA from file if exists
    ua_path = f"{user_dir}/ua.txt"
    if os.path.exists(ua_path):
        with open(ua_path, "r") as f:
            ua = f.read().strip()
    
    # Fallback to a modern stable UA if file read failed or empty
    if not ua or len(ua) < 10:
         ua = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
            
    # 🔥 FIX: Use edith.xiaohongshu.com with updated headers
    headers = {
        'User-Agent': ua,
        'Referer': 'https://www.xiaohongshu.com/',
        'Origin': 'https://www.xiaohongshu.com',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Sec-Ch-Ua': '"Chromium";v="122", "Google Chrome";v="122"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"macOS"',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache'
    }
    
    print(f"[{userId}] 🔄 Fetching profile from XHS (edith)...")
    print(f"[{userId}] 🍪 Cookie count: {len(cookie_dict)}")
    print(f"[{userId}] 🕵️ UA used: {ua[:50]}...")
    
    try:
        resp = requests.get(
            'https://edith.xiaohongshu.com/api/sns/web/v1/user/selfinfo',
            cookies=cookie_dict,
            headers=headers,
            timeout=15
        )
    except Exception as e:
        print(f"[{userId}] ❌ XHS API Request Exception: {e}")
        raise HTTPException(status_code=502, detail="Failed to connect to XHS API")
        
    if resp.status_code != 200:
        body_preview = (resp.text or "")[:500]  # 截断避免太长
        print(f"[{userId}] ❌ XHS API Error {resp.status_code} Body: {body_preview}")
        # 🔥 返回字符串格式的 detail（兼容前端）
        raise HTTPException(
            status_code=resp.status_code, 
            detail=f"XHS API Error {resp.status_code}: {body_preview}"
        )
        
    # The response structure from edith
    data = resp.json()
    if not data.get("success") and data.get("code") != 0:
         print(f"[{userId}] ❌ XHS API Response Invalid: {data}")
         raise HTTPException(
             status_code=400, 
             detail=f"XHS API returned invalid response (code={data.get('code')}): {str(data)[:300]}"
         )
         
    profile = data.get("data", {})
    nickname = profile.get("nickname", "Unknown")
    avatar = profile.get("images", "").split("?")[0]
    red_id = profile.get("red_id", "")
    xhs_real_id = profile.get("user_id", "")
    
    print(f"[{userId}] ✅ Got Profile: {nickname} (ID: {red_id})")
    
    # 4. Sync to Supabase
    supabase_url = os.getenv("SUPABASE_URL")
    # Prefer Service Role Key for writing to restricted tables
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    
    if supabase_url and supabase_key:
        try:
            # 4.1 Calculate Session Hash
            import hashlib
            session_hash = "unknown_session"
            if web_session:
                session_hash = hashlib.sha256(web_session.encode()).hexdigest()[:32]
            
            # 4.2 Upsert xhs_accounts
            # First check if account exists by hash
            sb_headers = {
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
                "Prefer": "return=representation"
            }
            
            # Check existing
            check_res = requests.get(
                f"{supabase_url}/rest/v1/xhs_accounts?xhs_session_hash=eq.{session_hash}&select=id",
                headers=sb_headers
            )
            
            account_id = None
            if check_res.ok and len(check_res.json()) > 0:
                account_id = check_res.json()[0]['id']
                # Update
                print(f"[{userId}] 🔄 Updating existing account {account_id}...")
                requests.patch(
                    f"{supabase_url}/rest/v1/xhs_accounts?id=eq.{account_id}",
                    json={
                        "nickname": nickname,
                        "avatar_url": avatar,
                        "red_id": red_id,
                        "xhs_real_user_id": xhs_real_id,
                        "updated_at": datetime.now().isoformat()
                    },
                    headers=sb_headers
                )
            else:
                # Insert
                print(f"[{userId}] ➕ Creating new account record...")
                insert_res = requests.post(
                    f"{supabase_url}/rest/v1/xhs_accounts",
                    json={
                        "xhs_session_hash": session_hash,
                        "nickname": nickname,
                        "avatar_url": avatar,
                        "red_id": red_id,
                        "xhs_real_user_id": xhs_real_id
                    },
                    headers=sb_headers
                )
                if insert_res.ok and len(insert_res.json()) > 0:
                    account_id = insert_res.json()[0]['id']
            
            # 4.3 Bind to User (if account_id and supabase_uuid valid)
            # userId format: user_{uuid}_prome
            if account_id and userId.startswith("user_") and "_prome" in userId:
                supabase_uuid = userId.replace("user_", "").replace("_prome", "")
                
                print(f"[{userId}] 🔗 Binding account {account_id} to user {supabase_uuid}...")
                
                # Check binding
                requests.post(
                    f"{supabase_url}/rest/v1/user_xhs_account_bindings",
                    json={
                        "supabase_uuid": supabase_uuid,
                        "xhs_account_id": account_id,
                        "is_default": False # Or True if first?
                    },
                    headers={**sb_headers, "Prefer": "resolution=merge-duplicates"}
                )
                
            print(f"[{userId}] ✅ Sync to Supabase complete")
            
        except Exception as e:
            print(f"[{userId}] ⚠️ Supabase Sync Error: {e}")
            # Don't fail the request just because sync failed, return profile anyway
            
    return {
        "success": True,
        "data": {
            "nickname": nickname,
            "avatar": avatar,
            "red_id": red_id,
            "desc": profile.get("desc", "")
        }
    }


class ConnectionManager:
    """Manage WebSocket connections from Chrome extensions"""
    
    def __init__(self):
        # user_id -> WebSocket connection
        self.active_connections: Dict[str, WebSocket] = {}
        # user_id -> publish tasks queue
        self.publish_queues: Dict[str, List[Dict]] = {}
    
    async def connect(self, user_id: str, websocket: WebSocket):
        """Accept and store WebSocket connection"""
        await websocket.accept()
        self.active_connections[user_id] = websocket
        if user_id not in self.publish_queues:
            self.publish_queues[user_id] = []
        print(f"[WebSocket] User {user_id} connected. Total: {len(self.active_connections)}")
    
    def disconnect(self, user_id: str):
        """Remove WebSocket connection"""
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        print(f"[WebSocket] User {user_id} disconnected. Total: {len(self.active_connections)}")
    
    def is_connected(self, user_id: str) -> bool:
        """Check if user is connected via WebSocket"""
        return user_id in self.active_connections
    
    async def send_message(self, user_id: str, message: dict):
        """Send message to specific user"""
        if user_id in self.active_connections:
            websocket = self.active_connections[user_id]
            try:
                await websocket.send_json(message)
                return True
            except Exception as e:
                print(f"[WebSocket] Failed to send to {user_id}: {e}")
                self.disconnect(user_id)
                return False
        return False
    
    def add_task(self, user_id: str, task: dict):
        """Add publish task to user's queue"""
        if user_id not in self.publish_queues:
            self.publish_queues[user_id] = []
        self.publish_queues[user_id].append(task)
    
    def get_tasks(self, user_id: str) -> List[Dict]:
        """Get user's publish tasks"""
        return self.publish_queues.get(user_id, [])


# Global connection manager
ws_manager = ConnectionManager()


def verify_extension_token(token: str) -> Optional[str]:
    """
    Verify extension token and return user_id
    For now, use simple token format: "ext_{user_id}"
    In production, use proper JWT validation
    """
    if token and token.startswith("ext_"):
        return token.replace("ext_", "")
    # Fallback: use WORKER_SECRET as token
    if token == WORKER_SECRET:
        return "default_user"
    return None


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = None):
    """
    WebSocket endpoint for Chrome extension
    URL: wss://your-backend/ws?token=ext_{user_id}
    """
    
    # Verify token
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return
    
    user_id = verify_extension_token(token)
    if not user_id:
        await websocket.close(code=4002, reason="Invalid token")
        return
    
    # Accept connection
    await ws_manager.connect(user_id, websocket)
    
    try:
        while True:
            # Receive messages from extension
            data = await websocket.receive_json()
            await handle_extension_message(user_id, data)
            
    except WebSocketDisconnect:
        ws_manager.disconnect(user_id)
    except Exception as e:
        print(f"[WebSocket] Error for {user_id}: {e}")
        ws_manager.disconnect(user_id)


async def handle_extension_message(user_id: str, message: dict):
    """Handle messages from Chrome extension"""
    msg_type = message.get("type")
    data = message.get("data", {})
    
    print(f"[WebSocket] Received from {user_id}: {msg_type}")
    
    if msg_type == "ping":
        # Heartbeat response
        await ws_manager.send_message(user_id, {"type": "pong"})
    
    elif msg_type == "publish_result":
        # Extension completed a publish task
        task_id = data.get("taskId")
        success = data.get("success")
        error_msg = data.get("message", "")
        
        print(f"[WebSocket] Task {task_id} {'completed' if success else 'failed'}: {error_msg}")
        # Here you can update database, notify other services, etc.
    
    elif msg_type == "login_status":
        # Extension reported XHS login status
        is_logged_in = data.get("isLoggedIn", False)
        print(f"[WebSocket] User {user_id} XHS login: {is_logged_in}")


@app.get("/api/v1/publish-plan")
async def get_publish_plan(authorization: str = Header(None)):
    """
    Get publish plan for Chrome extension
    Used by extension to sync tasks
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    token = authorization.replace("Bearer ", "")
    user_id = verify_extension_token(token)
    
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    tasks = ws_manager.get_tasks(user_id)
    return {"tasks": tasks}


class ExtensionPublishRequest(BaseModel):
    title: str
    content: str
    images: List[str] = []
    tags: List[str] = []
    user_id: str = "default_user"

@app.post("/api/v1/extension/publish")
async def trigger_extension_publish(
    request: ExtensionPublishRequest,
    authorization: str = Header(None)
):
    """
    Trigger publish via Chrome extension
    This sends a publish command to the connected extension
    """
    if authorization != f"Bearer {WORKER_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Check if extension is connected
    if not ws_manager.is_connected(request.user_id):
        raise HTTPException(
            status_code=400,
            detail="Chrome extension not connected. Please ensure extension is installed and connected."
        )
    
    # Create publish task
    task_id = f"task_{int(datetime.now().timestamp())}"
    task = {
        "id": task_id,
        "title": request.title,
        "content": request.content,
        "images": request.images,
        "tags": request.tags,
        "scheduledTime": datetime.now().isoformat(),
        "status": "executing"
    }
    
    # Add to queue
    ws_manager.add_task(request.user_id, task)
    
    # Send to extension immediately
    await ws_manager.send_message(request.user_id, {
        "type": "publish",
        "data": task
    })
    
    return {
        "success": True,
        "taskId": task_id,
        "message": "Publish command sent to extension"
    }
