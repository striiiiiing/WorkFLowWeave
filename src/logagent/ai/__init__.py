"""AI 模块公共入口：服务、渠道协议、OpenAI 兼容实现和取消通知。"""

from .channels import AIChannel, ChannelFactory, OpenAIChannel, OpenAIChannelFactory
from .service import AIService, CancellationNotice

__all__ = [
    "AIChannel", "AIService", "CancellationNotice", "ChannelFactory",
    "OpenAIChannel", "OpenAIChannelFactory",
]
