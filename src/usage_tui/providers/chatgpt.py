"""Explicitly unresolved ordinary ChatGPT weekly usage; never a Codex adapter."""

from datetime import datetime

from usage_tui.domain import (
    REQUIRED_METRIC_IDS,
    Account,
    Diagnostic,
    FetchState,
    Metric,
    MetricState,
    ProviderId,
    ResolvedCredential,
    Snapshot,
    SourceKind,
    SourceRef,
)

_PROVIDER = ProviderId.CHATGPT_SUBSCRIPTION
_SOURCE = SourceRef(SourceKind.UNRESOLVED, "chatgpt.subscription.weekly")
_DETAIL = (
    "普通 ChatGPT 每周用量的只读接口、认证与模型窗口语义尚未验证。"
    "保存凭据不会启用查询；不使用 Codex/Work 额度替代。 "
    "Ordinary ChatGPT weekly usage has no verified read contract; "
    "stored credentials do not enable retrieval."
)


class ChatGPTProvider:
    """Publish the missing upstream contract without transport or credential access."""

    requires_credential = False
    metric_ids = REQUIRED_METRIC_IDS[_PROVIDER]

    async def fetch(
        self, account: Account, credential: ResolvedCredential | None, now: datetime
    ) -> Snapshot:
        return Snapshot(
            account_id=account.id,
            metrics=(
                Metric(
                    id=self.metric_ids[0],
                    label="ChatGPT 每周",
                    state=MetricState.BLOCKED,
                    source=_SOURCE,
                    detail=_DETAIL,
                ),
            ),
            grants=(),
            fetch_state=FetchState.UPSTREAM_CONTRACT_MISSING,
            attempted_at=now,
            diagnostic=Diagnostic("upstream_contract_missing"),
        )
