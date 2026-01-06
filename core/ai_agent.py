import os
import json
import time
import asyncio
import logging
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
import anthropic
import requests
from pydantic import BaseModel

# Supabase for persistent storage
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    logging.warning("Supabase client not available, falling back to file storage")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class UserProfile(BaseModel):
    userId: str
    productName: str
    targetAudience: str
    marketingGoal: str
    postFrequency: str
    brandStyle: str
    reviewMode: str

class DailyTask(BaseModel):
    scheduledTime: str  # ISO format
    contentType: str
    title: str
    content: str
    imagePrompts: List[str]
    imageUrls: List[str] = []
    hashtags: List[str]
    status: str  # 'planned', 'generating', 'ready', 'published'

class WeeklyPlan(BaseModel):
    days: List[Dict[str, Any]]

class ContentStrategy(BaseModel):
    keyThemes: List[str]
    contentTypes: List[str]
    optimalTimes: List[str]
    hashtags: List[str]
    trendingTopics: List[str]

class ImageGenerationService:
    def __init__(self, gemini_key: Optional[str] = None, unsplash_key: Optional[str] = None):
        self.gemini_key = gemini_key
        self.unsplash_key = unsplash_key

    async def generate_image(self, prompt: str, user_id: str) -> Dict[str, str]:
        """Generate image using Gemini or fallback to Unsplash/Placeholder"""
        if self.gemini_key:
            result = await self._generate_with_gemini(prompt)
            if result:
                return result
        
        if self.unsplash_key:
            result = await self._get_from_unsplash(prompt)
            if result:
                return result
                
        return self._get_placeholder_image()

    async def _generate_with_gemini(self, prompt: str) -> Optional[Dict[str, str]]:
        try:
            # Use configured Gemini model (default to 2.0 Flash Exp)
            model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={self.gemini_key}"
            headers = {"Content-Type": "application/json"}
            
            full_prompt = f"{prompt}, high quality, vibrant colors, social media ready, photorealistic"
            
            payload = {
                "contents": [{
                    "parts": [{"text": f"Generate an image of: {full_prompt}"}]
                }],
                "generationConfig": {
                    "temperature": 0.7,
                    "maxOutputTokens": 1024
                }
            }
            
            response = requests.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                logger.error(f"Gemini API error: {response.text}")
                return None
                
            data = response.json()
            
            # Check for image data in response
            if "candidates" in data and data["candidates"]:
                parts = data["candidates"][0]["content"]["parts"]
                for part in parts:
                    if "inlineData" in part and part["inlineData"]["mimeType"].startswith("image/"):
                        # Found image!
                        mime_type = part["inlineData"]["mimeType"]
                        base64_data = part["inlineData"]["data"]
                        
                        # Save locally
                        import base64
                        ext = ".png" if "png" in mime_type else ".jpg"
                        filename = f"gemini_{int(time.time())}{ext}"
                        filepath = os.path.join("data/images", filename)
                        os.makedirs("data/images", exist_ok=True)
                        
                        with open(filepath, "wb") as f:
                            f.write(base64.b64decode(base64_data))
                            
                        # Return local URL (assuming served via static files or just path)
                        # For now, returning absolute path or relative path that frontend can access?
                        # Frontend is React, Backend is FastAPI. We need to serve 'data/images'.
                        # I will add static file serving to main.py later.
                        return {
                            "url": f"/images/{filename}", 
                            "source": "gemini"
                        }
            
            logger.warning("No image data found in Gemini response")
            return None

        except Exception as e:
            logger.error(f"Gemini generation failed: {e}")
            return None

    async def _get_from_unsplash(self, prompt: str) -> Optional[Dict[str, str]]:
        # Placeholder for Unsplash logic
        return None

    def _get_placeholder_image(self) -> Dict[str, str]:
        return {
            "url": "https://via.placeholder.com/1080x1080?text=AI+Generated+Image",
            "source": "placeholder"
        }

class AutoContentManager:
    def __init__(self, data_dir: str = "data/auto-content"):
        self.data_dir = data_dir
        self.anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.image_service = ImageGenerationService(
            gemini_key=os.getenv("GEMINI_API_KEY"),
            unsplash_key=os.getenv("UNSPLASH_ACCESS_KEY")
        )
        self.user_profiles: Dict[str, UserProfile] = {}
        self.content_plans: Dict[str, Dict] = {} # Stores strategy, weeklyPlan, dailyTasks
        self.generation_status: Dict[str, str] = {} # 'idle', 'generating', 'completed', 'failed'
        
        # Initialize Supabase client
        self.supabase: Optional[Client] = None
        if SUPABASE_AVAILABLE:
            supabase_url = os.getenv("SUPABASE_URL")
            supabase_key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_ANON_KEY")
            if supabase_url and supabase_key:
                try:
                    self.supabase = create_client(supabase_url, supabase_key)
                    logger.info("✅ Supabase client initialized for content persistence")
                except Exception as e:
                    logger.error(f"❌ Failed to initialize Supabase client: {e}")
        
        os.makedirs(self.data_dir, exist_ok=True)
        self._load_persisted_data()

    def _load_persisted_data(self):
        """从 Supabase 或本地文件加载持久化数据"""
        # 优先从 Supabase 加载
        if self.supabase:
            try:
                logger.info("📥 Loading content plans from Supabase...")
                response = self.supabase.table('xhs_content_plans').select('*').execute()
                for row in response.data:
                    user_id = row['user_id']
                    if row.get('user_profile'):
                        self.user_profiles[user_id] = UserProfile(**row['user_profile'])
                    if row.get('daily_tasks') or row.get('strategy'):
                        self.content_plans[user_id] = {
                            'strategy': row.get('strategy'),
                            'weeklyPlan': row.get('weekly_plan'),
                            'dailyTasks': row.get('daily_tasks', [])
                        }
                        self.generation_status[user_id] = row.get('generation_status', 'completed')
                logger.info(f"✅ Loaded {len(response.data)} content plans from Supabase")
                return
            except Exception as e:
                logger.error(f"❌ Failed to load from Supabase: {e}")
                # Fallback to file storage
        
        # Fallback: 从本地文件加载
        try:
            if not os.path.exists(self.data_dir):
                return
                
            for filename in os.listdir(self.data_dir):
                if filename.endswith(".json"):
                    user_id = filename.replace(".json", "")
                    with open(os.path.join(self.data_dir, filename), 'r') as f:
                        data = json.load(f)
                        if "userProfile" in data:
                            self.user_profiles[user_id] = UserProfile(**data["userProfile"])
                        if "contentPlan" in data:
                            self.content_plans[user_id] = data["contentPlan"]
                            self.generation_status[user_id] = 'completed'
        except Exception as e:
            logger.error(f"Failed to load persisted data: {e}")

    def _save_data(self, user_id: str):
        """保存用户数据到 Supabase 和本地文件"""
        user_profile = self.user_profiles.get(user_id)
        content_plan = self.content_plans.get(user_id)
        status = self.generation_status.get(user_id, 'idle')
        
        # 保存到 Supabase
        if self.supabase:
            try:
                data = {
                    'user_id': user_id,
                    'user_profile': user_profile.dict() if user_profile else None,
                    'strategy': content_plan.get('strategy') if content_plan else None,
                    'weekly_plan': content_plan.get('weeklyPlan') if content_plan else None,
                    'daily_tasks': content_plan.get('dailyTasks', []) if content_plan else [],
                    'generation_status': status,
                    'updated_at': datetime.now().isoformat()
                }
                
                # Upsert (insert or update)
                self.supabase.table('xhs_content_plans').upsert(
                    data, 
                    on_conflict='user_id'
                ).execute()
                
                logger.info(f"✅ Saved content plan for {user_id} to Supabase")
            except Exception as e:
                logger.error(f"❌ Failed to save to Supabase: {e}")
        
        # 同时保存到本地文件作为备份
        try:
            data = {
                "userProfile": user_profile.dict() if user_profile else None,
                "contentPlan": content_plan,
                "savedAt": datetime.now().isoformat()
            }
            with open(os.path.join(self.data_dir, f"{user_id}.json"), 'w') as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save local backup for {user_id}: {e}")

    async def start_auto_mode(self, profile_data: Dict):
        """Start the auto content generation process"""
        user_id = profile_data["userId"]
        profile = UserProfile(**profile_data)
        self.user_profiles[user_id] = profile
        self.generation_status[user_id] = "generating"
        
        # Run in background
        asyncio.create_task(self._generate_content_flow(user_id))

    async def _generate_content_flow(self, user_id: str):
        try:
            profile = self.user_profiles[user_id]
            logger.info(f"Starting content generation for {user_id}")

            # 1. Create Strategy
            strategy = await self._create_content_strategy(profile)
            
            # 2. Generate Weekly Plan
            weekly_plan = await self._generate_weekly_plan(profile, strategy)
            
            # 3. Generate Daily Tasks (Detailed)
            daily_tasks = await self._generate_daily_tasks(profile, weekly_plan)
            
            # Save everything
            self.content_plans[user_id] = {
                "strategy": strategy.dict(),
                "weeklyPlan": weekly_plan.dict(),
                "dailyTasks": [t.dict() for t in daily_tasks]
            }
            self.generation_status[user_id] = "completed"
            self._save_data(user_id)
            logger.info(f"Content generation completed for {user_id}")

        except Exception as e:
            logger.error(f"Content generation failed for {user_id}: {e}")
            self.generation_status[user_id] = "failed"

    async def _call_claude(self, prompt: str, max_tokens: int = 2000) -> str:
        """Helper to call Claude API"""
        try:
            model = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
            message = self.anthropic_client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}]
            )
            return message.content[0].text
        except Exception as e:
            logger.error(f"Claude API call failed: {e}")
            raise

    def _clean_json(self, text: str) -> str:
        """Clean markdown code blocks from JSON string"""
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()

    async def _create_content_strategy(self, profile: UserProfile) -> ContentStrategy:
        prompt = f"""
        你是一位资深的小红书运营专家。请为以下产品制定详细的内容营销策略：
        产品：{profile.productName}
        目标客户：{profile.targetAudience}
        营销目标：{profile.marketingGoal}
        风格：{profile.brandStyle}

        请返回JSON格式，包含以下字段：
        - keyThemes: 5个核心主题
        - contentTypes: 8种内容类型
        - optimalTimes: 3个最佳发布时间
        - hashtags: 20个热门标签
        - trendingTopics: 3个相关趋势
        """
        response = await self._call_claude(prompt)
        data = json.loads(self._clean_json(response))
        return ContentStrategy(**data)

    async def _generate_weekly_plan(self, profile: UserProfile, strategy: ContentStrategy) -> WeeklyPlan:
        prompt = f"""
        基于以下策略为{profile.productName}制定7天发布计划：
        核心主题：{', '.join(strategy.keyThemes)}
        发布频率：{profile.postFrequency}

        请返回JSON格式：
        {{
            "days": [
                {{
                    "date": "YYYY-MM-DD",
                    "posts": [
                        {{
                            "theme": "主题",
                            "type": "类型",
                            "scheduledTime": "HH:MM"
                        }}
                    ]
                }}
            ]
        }}
        """
        response = await self._call_claude(prompt)
        data = json.loads(self._clean_json(response))
        return WeeklyPlan(**data)

    async def _generate_daily_tasks(self, profile: UserProfile, weekly_plan: WeeklyPlan) -> List[DailyTask]:
        tasks = []
        for day in weekly_plan.days:
            for post in day.get("posts", []):
                task = await self._create_detailed_task(profile, post, day["date"])
                tasks.append(task)
        return tasks

    async def _create_detailed_task(self, profile: UserProfile, post: Dict, date_str: str) -> DailyTask:
        prompt = f"""
        为小红书生成一篇文案：
        产品：{profile.productName}
        主题：{post['theme']}
        类型：{post['type']}
        风格：{profile.brandStyle}

        请返回JSON格式：
        {{
            "title": "标题(20字内)",
            "content": "正文(带emoji)",
            "imagePrompts": ["4个英文图片提示词"],
            "hashtags": ["5-8个标签"]
        }}
        """
        response = await self._call_claude(prompt)
        data = json.loads(self._clean_json(response))
        
        # Generate images (Mock/Placeholder for now to speed up)
        image_urls = []
        for prompt in data["imagePrompts"]:
            img_res = await self.image_service.generate_image(prompt, profile.userId)
            image_urls.append(img_res["url"])

        # Construct scheduled time
        scheduled_time = f"{date_str}T{post.get('scheduledTime', '09:00')}:00"

        return DailyTask(
            scheduledTime=scheduled_time,
            contentType=post['type'],
            title=data['title'],
            content=data['content'],
            imagePrompts=data['imagePrompts'],
            imageUrls=image_urls,
            hashtags=data['hashtags'],
            status='ready'
        )

    def get_strategy(self, user_id: str) -> Optional[Dict]:
        if user_id in self.content_plans:
            return self.content_plans[user_id].get("strategy")
        return None

    def get_daily_tasks(self, user_id: str) -> List[Dict]:
        if user_id in self.content_plans:
            return self.content_plans[user_id].get("dailyTasks", [])
        return []

    def get_status(self, user_id: str) -> str:
        return self.generation_status.get(user_id, "idle")
