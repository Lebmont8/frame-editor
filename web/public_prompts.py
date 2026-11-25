"""Load caller-supplied instructions; no private templates are distributed."""
import json,os
from pathlib import Path

def required_prompt(key, **context):
    filename=os.environ.get("PUBLIC_PROMPTS_FILE","")
    if not filename:
        raise RuntimeError("Configure PUBLIC_PROMPTS_FILE before using AI features")
    path=Path(filename)
    if path.stat().st_size>1024*1024:
        raise ValueError("Prompt configuration exceeds 1 MiB")
    payload=json.loads(path.read_text(encoding="utf-8"))
    text=payload.get(key) if isinstance(payload,dict) else None
    if not isinstance(text,str) or not text.strip() or len(text)>64000:
        raise ValueError("Missing or invalid caller-supplied prompt: "+key)
    return text+("\n\n"+json.dumps(context,ensure_ascii=False,default=str) if context else "")
