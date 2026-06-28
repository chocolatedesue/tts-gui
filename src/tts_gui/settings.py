import json
from pathlib import Path

DEFAULT_CLEAN_PROMPT = '将文本转换为适合TTS朗读的纯文本：移除markdown格式、语气词、口头禅，使句子通顺，保留核心内容。只输出结果。'
SETTINGS_FILE = Path.home() / '.config' / 'tts-gui' / 'settings.json'

SCHEMA = {
    'api_url': ('api_url', '', str),
    'api_key': ('api_key', '', str),
    'api_model': ('api_model', '', str),
    'clean_prompt': ('clean_prompt', DEFAULT_CLEAN_PROMPT, str),
    'rate': ('rate_value', 0, float),
    'pitch': ('pitch_value', 0, float),
    'volume': ('volume_value', 0, float),
    'clean_enabled': ('clean_enabled', True, bool),
    'device_index': ('current_device_index', 0, int),
    'player_volume': ('player_volume', 80, float),
}


def load(path=None):
    f = path or SETTINGS_FILE
    data = {}
    try:
        if f.exists():
            data = json.loads(f.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        data = {}
    return {k: schema[2](data.get(k, schema[1])) for k, schema in SCHEMA.items()}


def save(data, path=None):
    f = path or SETTINGS_FILE
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def apply_to(win, data):
    for key, (attr, default, _) in SCHEMA.items():
        setattr(win, attr, data.get(key, default))


def capture_from(win):
    return {key: getattr(win, attr, default) for key, (attr, default, _) in SCHEMA.items()}
