"""Thin wrapper over any OpenAI-compatible API, so the model is swappable."""
import json, os, re
from openai import OpenAI

_client = None

def _get():
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ["LLM_API_KEY"], base_url=os.getenv("LLM_BASE_URL"))
    return _client

def chat(prompt, system="", model_env="GEN_MODEL", json_mode=False, temperature=0.4):
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    kw = {"response_format": {"type": "json_object"}} if json_mode else {}
    r = _get().chat.completions.create(model=os.environ[model_env], messages=msgs,
                                       temperature=temperature, **kw)
    return r.choices[0].message.content

def parse_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    return json.loads(text)
