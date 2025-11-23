import os
import requests
import uuid

def download_video(url: str, temp_dir: str = "/tmp") -> str:
    """
    Download video to temporary directory and return local path
    """
    try:
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)
            
        # Generate random filename to avoid conflicts
        file_name = f"{uuid.uuid4()}.mp4"
        file_path = os.path.join(temp_dir, file_name)
        
        print(f"📥 Downloading video: {url}")
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(file_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
                    
        print(f"✅ Download complete: {file_path}")
        return file_path
    except Exception as e:
        raise Exception(f"Video download failed: {str(e)}")
