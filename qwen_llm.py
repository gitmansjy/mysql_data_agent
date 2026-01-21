# qwen_llm.py

from langchain_core.language_models import BaseLanguageModel
from langchain_core.outputs import Generation, LLMResult
from typing import Any, List, Optional
import dashscope
from dashscope import Generation as DashGen
import os
import logging
import asyncio
from pathlib import Path
from datetime import datetime

# 尝试从本地 config.py 读取 API Key（若存在），优先使用本地配置
try:
    from config import DASHSCOPE_API_KEY as CONFIG_API_KEY  # type: ignore
except Exception:
    CONFIG_API_KEY = None

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
_DEBUG_LOG = Path("qwen_debug.log")

def _write_debug_log(entry: str):
    try:
        _DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _DEBUG_LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.utcnow().isoformat()}] {entry}\n")
    except Exception:
        logger.exception("无法写入 debug 日志")

class Qwen(BaseLanguageModel):
    """
    通义千问模型封装，兼容 LangChain 接口
    支持 qwen-max, qwen-plus, qwen-turbo, qwen-7b-chat 等
    """
    model_name: str = "qwen-max"
    temperature: float = 0.2
    max_retries: int = 3
    api_key: Optional[str] = None

    def __init__(
        self,
        model: str = "qwen-max",
        temperature: float = 0.2,
        max_retries: int = 3,
        api_key: str = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.model_name = model
        self.temperature = temperature
        self.max_retries = max_retries
        # 优先级：api 参数 > config.py 中的 CONFIG_API_KEY > 环境变量
        self.api_key = api_key or CONFIG_API_KEY or os.getenv("DASHSCOPE_API_KEY")

        if not self.api_key:
            raise ValueError(
                "❌ 缺少 DASHSCOPE_API_KEY。请通过环境变量或参数传入。"
            )

        # 设置全局 API Key
        dashscope.api_key = self.api_key

    def _call(self, prompt: str, **kwargs) -> str:
        """调用 Qwen 模型生成响应"""
        # 校验 prompt，避免将空内容发给远端接口导致不明确的错误
        if not prompt or (isinstance(prompt, str) and prompt.strip() == ""):
            logger.error("调用异常: prompt 为空")
            return "[错误] prompt 为空，请提供有效的输入。"
        # 根据 Bailian / DashScope 文档：Python SDK 接受 `messages` 参数，
        # 避免使用嵌套的 `input` 结构以减少不同适配器间的不兼容。
        call_variants = [
            {"messages": [{"role": "user", "content": prompt}]},
            {"prompt": prompt},
        ]

        last_exc = None
        for attempt in range(self.max_retries):
            for variant in call_variants:
                try:
                    # 仅传入明确支持的简单参数，避免透传 LangChain 的复杂对象（如 CallbackManager）
                    call_kwargs = {
                        "model": self.model_name,
                        "temperature": self.temperature,
                    }
                    call_kwargs.update(variant)

                    # 清洗 call_kwargs：移除不可序列化或明显为运行时回调管理器的字段
                    def _is_simple(v):
                        if v is None:
                            return True
                        if isinstance(v, (str, int, float, bool)):
                            return True
                        if isinstance(v, (list, tuple)):
                            return all(_is_simple(x) for x in v)
                        if isinstance(v, dict):
                            return all(isinstance(k, (str, int)) and _is_simple(val) for k, val in v.items())
                        return False

                    safe_kwargs = {}
                    for k, v in call_kwargs.items():
                        if _is_simple(v):
                            safe_kwargs[k] = v
                        else:
                            _write_debug_log(f"DROP_UNSERIALIZABLE key={k} type={type(v)}")

                    # 如果 API Key 含非 ASCII，记录并告警（可能导致 header 编码错误）
                    try:
                        if isinstance(self.api_key, str) and not all(ord(c) < 128 for c in self.api_key):
                            _write_debug_log("WARNING non-ascii API key detected; header encoding may fail")
                    except Exception:
                        pass

                    response = DashGen.call(**safe_kwargs)

                    # 解析返回：优先依据 docs 中的 output.choices[].message.content
                    content = None
                    output = getattr(response, "output", None)
                    if output is not None:
                        try:
                            choices = getattr(output, "choices", None)
                            if choices and len(choices) > 0:
                                first = choices[0]
                                # 支持属性和 dict 两种访问方式
                                msg = getattr(first, "message", None) or (first.get("message") if isinstance(first, dict) else None)
                                if msg is not None:
                                    content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else None)
                        except Exception:
                            content = None

                        if not content:
                            # fallback to output.text
                            try:
                                content = getattr(output, "text", None) or (output.get("text") if isinstance(output, dict) else None)
                            except Exception:
                                content = None

                    # 其它可能的字段
                    if not content:
                        content = getattr(response, "text", None) or (response.get("text") if isinstance(response, dict) else None)

                    if content:
                        content = content.strip()
                        if content:
                            return content
                        else:
                            logger.warning("模型返回空内容（空字符串）")
                            return "[错误] 模型返回空内容"
                    else:
                        # 记录响应属性快照以便调试
                        try:
                            attrs = list(dir(response))
                        except Exception:
                            attrs = []
                        logger.warning(f"第 {attempt + 1} 次调用，variant={list(variant.keys())} 未解析到 content；response attrs: {attrs}")
                        _write_debug_log(f"NON200 variant={list(variant.keys())} attempt={attempt+1} resp_attrs={attrs}")
                        last_exc = f"no_content variant={list(variant.keys())}"
                except Exception as e:
                    logger.error(f"调用异常 (variant={list(variant.keys())}): {e}")
                    last_exc = e
                    try:
                        resp_attrs = list(dir(response)) if 'response' in locals() else 'N/A'
                    except Exception:
                        resp_attrs = 'N/A'
                    _write_debug_log(f"EXCEPTION variant={list(variant.keys())} attempt={attempt+1} exc={repr(e)} resp_attrs={resp_attrs}")

        # 所有尝试失败，记录并返回
        try:
            _write_debug_log(f"FAIL_ALL attempts={self.max_retries} last={repr(last_exc)}")
        except Exception:
            pass
        return f"[失败] 经过 {self.max_retries} 次重试仍无法调用成功：{last_exc} (详细日志见 qwen_debug.log)"

    def generate(self, prompts: List[str], **kwargs) -> LLMResult:
        """批量生成接口（用于兼容 LangChain 流程）"""
        generations = []
        for prompt in prompts:
            text = self._call(prompt, **kwargs)
            generations.append([Generation(text=text)])
        return LLMResult(generations=generations)

    # 同步兼容方法
    def predict(self, prompt: str, **kwargs) -> str:
        return self._call(prompt, **kwargs)

    def predict_messages(self, messages: Any, **kwargs) -> str:
        if isinstance(messages, (list, tuple)):
            parts = []
            for m in messages:
                if isinstance(m, dict):
                    parts.append(m.get("content", str(m)))
                else:
                    parts.append(getattr(m, "content", str(m)))
            text = "\n".join(parts)
        else:
            text = str(messages)
        return self._call(text, **kwargs)

    def invoke(self, prompt: Any, **kwargs) -> dict:
        text = self.predict(prompt if isinstance(prompt, str) else str(prompt), **kwargs)
        return {"text": text}

    def generate_prompt(self, *prompts: Any, **kwargs) -> LLMResult:
        # 支持多种调用方式：generate_prompt(['a','b']) 或 generate_prompt('a', stop)
        if len(prompts) == 1 and isinstance(prompts[0], (list, tuple)):
            items = [str(p) for p in prompts[0]]
        else:
            items = [str(p) for p in prompts]
        return self.generate(items, **kwargs)

    # 异步兼容方法（简单地将同步方法委托到线程池）
    async def apredict(self, prompt: str, **kwargs) -> str:
        return await asyncio.to_thread(self.predict, prompt, **kwargs)

    async def apredict_messages(self, messages: Any, **kwargs) -> str:
        return await asyncio.to_thread(self.predict_messages, messages, **kwargs)

    async def agenerate_prompt(self, prompts: List[Any], **kwargs) -> LLMResult:
        return await asyncio.to_thread(self.generate_prompt, prompts, **kwargs)

    @property
    def _llm_type(self) -> str:
        return "qwen"

    @property
    def _identifying_params(self) -> dict:
        return {
            "model_name": self.model_name,
            "temperature": self.temperature,
            "max_retries": self.max_retries
        }
