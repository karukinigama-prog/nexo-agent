import os
import re
import json
from groq import Groq

client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))

SYSTEM_PROMPT = """You are an elite software engineer. Your ONLY job is to return a JSON object — no prose, no explanation, no markdown outside the JSON.

Return EXACTLY this structure:
{
  "filename": "app.py",
  "language": "python",
  "code": "<complete source code as a single escaped string>"
}

Rules:
1. The code must be 100% complete, runnable, and bug-free.
2. Use Python + Flask or Python + http.server for web apps.
3. The server must listen on a PORT variable from environment: port = int(os.environ.get("PORT", 8080))
4. All HTML/CSS/JS must be inline (single file).
5. The app must be visually beautiful with a dark theme, gradients, and modern styling.
6. NEVER include markdown fences (```), never add commentary outside the JSON.
7. Return only valid JSON. Escape all quotes and newlines inside the code string properly.
"""

def generate_app_code(user_prompt: str) -> dict:
    """Call Groq and return {'filename': ..., 'language': ..., 'code': ...}"""
    
    enhanced_prompt = f"""Build this application: {user_prompt}

Requirements:
- Single Python file web application
- Uses Flask to serve an HTML page
- The HTML/CSS/JS must all be inline inside the Python file as a string
- Server listens on: port = int(os.environ.get("PORT", 8080))
- Beautiful, modern dark-themed UI with vibrant colors
- Fully functional with all requested features working
- No external dependencies except flask
"""
    
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": enhanced_prompt}
        ],
        temperature=0.3,
        max_tokens=8192,
    )
    
    raw = response.choices[0].message.content.strip()
    
    # Strip any accidental markdown fences
    raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```$", "", raw, flags=re.MULTILINE)
    raw = raw.strip()
    
    # Try to extract JSON if there's surrounding text
    json_match = re.search(r'\{[\s\S]*\}', raw)
    if json_match:
        raw = json_match.group(0)
    
    try:
        result = json.loads(raw)
        return result
    except json.JSONDecodeError:
        # Fallback: treat entire response as Python code
        return {
            "filename": "app.py",
            "language": "python",
            "code": raw
        }

def get_model_info() -> str:
    return "llama-3.3-70b-versatile"
