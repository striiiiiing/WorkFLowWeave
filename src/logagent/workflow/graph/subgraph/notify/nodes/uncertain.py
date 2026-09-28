from logagent.models import DeliveryResult, ErrorInfo


def uncertain(cid, oid):
    """生成投递不确定的失败回执，保留不得自动补发的错误原因。"""
    return DeliveryResult(
        channel_id=cid,
        output_id=oid,
        status="failed",
        attempts=1,
        error=ErrorInfo(
            code="delivery_uncertain",
            message="既有发送未获得可靠回执，不自动补发",
            details={"delivery_uncertain": True},
        ),
    )
