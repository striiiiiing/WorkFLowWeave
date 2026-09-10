from typing import List, Optional, Dict, Any
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field
from langchain_core.messages import BaseMessage
class RunStatus(str, Enum):
    Created = "created"
    InProgress = "in_progress"
    Completed = "completed"
    Failed = "failed"
    Cancelled = "cancelled"
class AgentRequest(BaseModel):
    """
    接收用户请求，看起来就像是投递到一个邮箱一样
    user_id：是用户的唯一标识符
    session_id：是会话的唯一标识符
    received_at：是请求到达的时间
    队列到runtime是丢失掉信息的
    同一session_id可以用多个user_id
    """
    model_config = ConfigDict(extra="ignore")
    input: List[BaseMessage] =  Field(default_factory=list)
    stream: bool = True
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    received_at: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class AgentResponse(BaseModel):
    """
    响应用户请求，消息给到渠道是指定session_id的，所以就不用写上session_id了
    """
    model_config = ConfigDict(extra="ignore")

    id: Optional[str] = None
    output: List[BaseMessage] = Field(default_factory=list)
    status: RunStatus = RunStatus.Completed
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

