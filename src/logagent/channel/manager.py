from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any

from logagent.errors import exception_error
from logagent.models import (
    CapabilityDescription,
    ChannelConfig,
    DeliveryResult,
    ErrorInfo,
    Notification,
)
from logagent.schema import validate_instance


class ChannelManager:
    def __init__(self, channel_register: Any, *, credentials: Any = None):
        self._register = channel_register
        self._credentials = credentials

    def describe(self) -> list[CapabilityDescription]:
        return [x.model_copy(deep=True) for x in self._register.describe()]

    def validate(self, config: ChannelConfig) -> None:
        channel = self._register.get(config.channel)
        if channel is None:
            raise ValueError("channel_missing")
        if "notification" not in channel.capabilities:
            raise ValueError("channel_not_notification")
        validate_instance(config.options, channel.options_schema, path=["options"])

    async def send(self, config: ChannelConfig, notification: Notification) -> DeliveryResult:
        if not config.enabled:
            return DeliveryResult(channel_id=config.id, output_id=notification.output_id, status="skipped", attempts=0)
        channel = self._register.get(config.channel)
        if channel is None:
            return DeliveryResult(channel_id=config.id, output_id=notification.output_id, status="failed", attempts=0, error=ErrorInfo(code="channel_missing", message="通知渠道未注册"))
        try:
            self.validate(config)
            credentials = self._credentials
            instance = await channel.create(deepcopy(config), credentials)
        except Exception as exc:
            return DeliveryResult(channel_id=config.id, output_id=notification.output_id, status="failed", attempts=0, error=exception_error(exc, code="channel_prepare_failed", message="通知渠道准备失败"))
        entered = False
        try:
            await asyncio.wait_for(instance.start(), config.timeout)
            entered = True
            await asyncio.wait_for(instance.send(notification), config.timeout)
            return DeliveryResult(channel_id=config.id, output_id=notification.output_id, status="success", attempts=1)
        except TimeoutError:
            return DeliveryResult(channel_id=config.id, output_id=notification.output_id, status="timeout", attempts=1 if entered else 0, error=ErrorInfo(code="delivery_timeout", message="通知发送超时", details={"delivery_uncertain": entered}))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return DeliveryResult(channel_id=config.id, output_id=notification.output_id, status="failed", attempts=1 if entered else 0, error=exception_error(exc, code="delivery_failed", message="通知发送失败", details={"delivery_uncertain": entered}))
        finally:
            try:
                await asyncio.wait_for(instance.stop(), config.timeout)
            except Exception:
                pass

    async def stop(self) -> None:
        return None
