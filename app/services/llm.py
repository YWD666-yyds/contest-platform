"""LLM 智能体服务：OpenAI 兼容 /chat/completions 调用 + 错误友好化。

- 配置由管理员在后台维护（api_base / api_key / model），学生不可见。
- 任何调用失败都会转化为面向学生与教师的提示（补全 API Key / 开放权限），
  且绝不向前端泄露 api_key 或上游原始响应。
"""
import json
import urllib.error
import urllib.request

# 前端展示用的友好提示（面向学生，附带老师可执行的动作）
FRIENDLY = {
    "auth": "智能体无法回复：API Key 无效或未配置。请联系老师：在管理后台「智能体设置」中补全 API Key，并确认已开放调用权限。",
    "forbidden": "智能体无法回复：当前账号没有开放该模型的调用权限（或额度已用尽）。请联系老师检查权限/额度后重试。",
    "not_found": "智能体无法回复：模型或接口地址配置有误。请联系老师检查管理后台的 LLM 配置。",
    "rate_limit": "智能体暂时繁忙（请求过于频繁或额度不足），请稍后再试；如持续出现请联系老师。",
    "server": "智能体服务暂时不可用，请稍后再试。",
    "timeout": "智能体响应超时，请稍后再试；如持续超时请联系老师检查后端网络。",
    "network": "无法连接智能体服务。请联系老师检查服务器网络与 LLM 配置。",
    "bad_response": "智能体返回了无法解析的内容，请稍后再试。",
    "disabled": "智能体对话功能尚未开放：老师还没有在后台配置 LLM。你可以先完成智能体设计。",
    "no_agent": "请先保存你的智能体设计，再开始对话。",
    "generic": "智能体暂时无法回复，请联系老师检查后台 LLM 配置（API Key / 开放权限）。",
}

TIMEOUT_SECONDS = 60

# 管理端「测试连接」用的技术性文案（区别于学生端友好文案，便于老师定位问题）
ADMIN_MESSAGES = {
    "auth": "API Key 无效或未配置（服务端返回 401）",
    "forbidden": "该 Key 未开放此模型权限或额度已用尽（403）",
    "not_found": "接口地址或模型名不存在（404）——请检查 Base URL 是否以 /v1 结尾、模型名是否为服务商提供的准确名称",
    "rate_limit": "请求过于频繁或额度不足（429）",
    "server": "模型服务端错误（5xx），请稍后再试",
    "timeout": "连接超时——地址不可达或网络被拦截",
    "network": "无法建立连接——请检查地址拼写、本机网络与防火墙",
    "bad_response": "服务可达，但返回内容无法解析——请确认该地址是 OpenAI 兼容接口（…/v1/chat/completions）",
    "generic": "调用失败，请检查配置",
}


class LLMError(Exception):
    def __init__(self, kind: str, detail: str = ""):
        self.kind = kind
        self.message = FRIENDLY.get(kind, FRIENDLY["generic"])
        self.admin_message = ADMIN_MESSAGES.get(kind, ADMIN_MESSAGES["generic"])
        super().__init__(self.message)


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "*" * (len(key) - 8) + key[-4:]


def llm_ready(cfg: dict) -> bool:
    return bool(cfg and cfg.get("enabled") and cfg.get("api_base") and cfg.get("api_key") and cfg.get("model"))


def build_system_prompt(agent: dict) -> str:
    """把学生的智能体设计组装成系统提示词（引导式字段 → 结构化人设）。"""
    lines = []
    prefix = (agent.get("system_prefix") or "").strip()
    if prefix:
        lines.append(prefix)
    name = (agent.get("name") or "").strip() or "便民小助手"
    lines.append(f"你是「{name}」，一个由学生围绕「智绘城市·AI便民智慧设施」主题设计的智能体。")
    if agent.get("role"):
        lines.append(f"【角色定位】{agent['role'].strip()}")
    if agent.get("audience"):
        lines.append(f"【服务对象】{agent['audience'].strip()}")
    if agent.get("scenario"):
        lines.append(f"【应用场景】{agent['scenario'].strip()}")
    if agent.get("problem"):
        lines.append(f"【要解决的便民问题】{agent['problem'].strip()}")
    if agent.get("skills"):
        lines.append(f"【功能与技能】{agent['skills'].strip()}")
    if agent.get("knowledge"):
        lines.append(f"【知识资料】请主要依据以下知识回答：\n{agent['knowledge'].strip()}")
    if agent.get("tone"):
        lines.append(f"【语气风格】{agent['tone'].strip()}")
    lines.append("请始终用中文回答，紧扣你的角色与便民场景，回答简洁、友好、有帮助；"
                 "遇到超出设计范围的问题，请说明你的能力边界并引导用户咨询老师或相关服务。")
    return "\n".join(lines)


def normalize_base_url(raw: str) -> str:
    """把用户粘贴的任意形式接口地址归一化为 OpenAI 兼容 Base URL（不含 /chat/completions）。

    兼容四种粘贴形式（以 Step Plan 为例）：
    - https://api.stepfun.com/step_plan/v1                      → 原样
    - https://api.stepfun.com/step_plan                         → …/step_plan/v1（Anthropic SDK 风格，无 /v1）
    - https://api.stepfun.com/step_plan/v1/chat/completions     → 剥掉完整请求路径
    - https://api.stepfun.com/step_plan/v1/messages             → 剥掉 Anthropic 路径
    另：纯域名（https://host）→ 补 /v1；结尾多余斜杠自动去除。
    """
    url = (raw or "").strip().rstrip("/")
    for suffix in ("/chat/completions", "/messages"):
        if url.lower().endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")
            break
    if url and not url.lower().endswith("/v1"):
        url += "/v1"
    return url


def full_chat_url(raw: str) -> str:
    """归一化后的完整 Chat Completions 请求地址（供界面提示与调用）。"""
    return normalize_base_url(raw) + "/chat/completions"


def _post_chat(cfg: dict, payload: dict) -> dict:
    url = full_chat_url(cfg["api_base"])
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode("utf-8"))


def chat(agent: dict, cfg: dict, history: list[dict], user_message: str) -> str:
    """
    调用 LLM 完成一轮对话。history: [{"role": "user"/"assistant", "content": "..."}]（不含本轮）。
    成功返回回复文本；失败抛 LLMError（message 为面向学生的友好提示）。
    """
    if not llm_ready(cfg):
        raise LLMError("disabled")

    messages = [{"role": "system", "content": build_system_prompt(agent)}]
    for h in history[-12:]:  # 只带最近 12 轮，控制成本
        if h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": h["content"][:2000]})
    messages.append({"role": "user", "content": user_message[:2000]})

    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": float(cfg.get("temperature", 0.7) or 0.7),
        "max_tokens": int(cfg.get("max_tokens", 800) or 800),
        "stream": False,
    }
    try:
        data = _post_chat(cfg, payload)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise LLMError("auth" if e.code == 401 else "forbidden")
        if e.code == 404:
            raise LLMError("not_found")
        if e.code == 429:
            raise LLMError("rate_limit")
        if 500 <= e.code < 600:
            raise LLMError("server")
        raise LLMError("generic")
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", None)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            raise LLMError("timeout")
        raise LLMError("network")
    except TimeoutError:
        raise LLMError("timeout")
    except Exception:
        raise LLMError("generic")

    try:
        choice = (data.get("choices") or [])[0]
        content = (choice.get("message") or {}).get("content") or ""
        if not content.strip():
            raise LLMError("bad_response")
        return content.strip()
    except LLMError:
        raise
    except Exception:
        raise LLMError("bad_response")


def test_connection(cfg: dict) -> tuple[bool, str]:
    """管理端「测试连接」：按给定配置发起真实调用，返回结果与说明。"""
    base = (cfg.get("api_base") or "").strip()
    if not base.startswith(("http://", "https://")):
        return False, "接口地址不合法（应以 http:// 或 https:// 开头）——常见写法如 https://api.siliconflow.cn/v1"
    if not llm_ready(cfg):
        missing = [n for n, ok in (("接口地址", cfg.get("api_base")), ("API Key", cfg.get("api_key")),
                                   ("模型名称", cfg.get("model"))) if not ok]
        return False, "配置不完整，缺少：" + "、".join(missing)
    try:
        reply = chat({"name": "连接测试"}, cfg, [], "请回复：连接成功")
        return True, f"连接成功，模型回复：{reply[:80]}"
    except LLMError as e:
        return False, e.admin_message
