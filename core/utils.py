import os
import shutil
import requests
import uuid

def download_file(url: str, temp_dir: str = "/tmp", suffix: str = ".mp4") -> str:
    """
    Download file to temporary directory and return local path
    """
    try:
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)
            
        # Generate random filename
        file_name = f"{uuid.uuid4()}{suffix}"
        file_path = os.path.join(temp_dir, file_name)
        
        print(f"📥 Downloading file: {url}")
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(file_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
                    
        print(f"✅ Download complete: {file_path}")
        return file_path
    except Exception as e:
        raise Exception(f"File download failed: {str(e)}")

def download_video(url: str, temp_dir: str = "/tmp") -> str:
    """Wrapper for backward compatibility"""
    return download_file(url, temp_dir, suffix=".mp4")


def clean_all_user_data(users_base_dir: str, current_user_id: str = None) -> None:
    """
    Clean all user data directories to ensure no session leakage.
    
    Args:
        users_base_dir: Base directory containing all user data directories (e.g., "data/users")
        current_user_id: Optional current user ID for logging purposes
    """
    if not os.path.exists(users_base_dir):
        return
        
    log_prefix = f"[{current_user_id}] " if current_user_id else ""
    print(f"{log_prefix}🧹 Cleaning ALL old user data directories...")
    
    for old_user_dir in os.listdir(users_base_dir):
        old_path = os.path.join(users_base_dir, old_user_dir)
        if os.path.isdir(old_path):
            try:
                shutil.rmtree(old_path)
                print(f"{log_prefix}🗑️ Cleaned: {old_user_dir}")
            except OSError as e:
                print(f"{log_prefix}⚠️ Failed to clean {old_user_dir}: {e}")
