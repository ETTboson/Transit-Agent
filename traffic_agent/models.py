"""Optional DeepSeek adapter. Selecting this backend explicitly enables external API calls."""
import json
import os
import time
import urllib.request


def deepseek_key():
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key or os.name != "nt":
        return key
    # A running desktop app may not inherit a recently changed Windows user variable.
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as registry:
            return str(winreg.QueryValueEx(registry, "DEEPSEEK_API_KEY")[0]).strip() or None
    except OSError:
        return None


class DeepSeekModel:
    def __init__(self, model="deepseek-v4-pro"):
        self.key = deepseek_key()
        if not self.key:
            raise ValueError("DEEPSEEK_API_KEY is missing. Configure it locally; do not paste it into chat.")
        self.model = model

    def decide(self, messages):
        # Same action protocol, tool permissions and loop budget as the local backend.
        body = {"model": self.model, "messages": messages, "stream": False,
                "response_format": {"type": "json_object"}, "thinking": {"type": "disabled"},
                "temperature": 0, "max_tokens": 1800}
        request = urllib.request.Request("https://api.deepseek.com/chat/completions",
                                         data=json.dumps(body).encode(), headers={
                                             "Content-Type": "application/json", "Authorization": f"Bearer {self.key}"})
        start = time.perf_counter()
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.load(response)
        choice = payload["choices"][0]
        content = choice["message"].get("content") or ""
        usage = payload.get("usage", {})
        stats = {"model": self.model, "provider": "deepseek", "elapsed_seconds": round(time.perf_counter() - start, 3),
                 "prompt_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens"),
                 "done_reason": choice.get("finish_reason"), "raw_response": content}
        try:
            return json.loads(content), stats
        except json.JSONDecodeError:
            return None, stats
