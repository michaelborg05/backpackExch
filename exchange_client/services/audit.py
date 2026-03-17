# services/audit.py
# ─────────────────────────────────────────────────────────────────────────────
# Shared helper for writing to config_audit_log.
#
# Usage (from any endpoint or service):
#
#   from services.audit import write_audit
#
#   write_audit(
#       db=db,                        # active SQLAlchemy session
#       type="indicator",
#       subtype="trend",
#       action="update",
#       entity_id=ind.id,
#       entity_name=f"{ind.indicator_type} ({profile_name})",
#       before={"params": old_params, "enabled": old_enabled},
#       after={"params": new_params,  "enabled": new_enabled},
#       changed_by="web_ui",          # optional, defaults to "web_ui"
#   )
#
# The function is intentionally fire-and-forget safe: if the audit write fails
# it logs the error but does NOT raise — the caller's main transaction is never
# rolled back because of an audit failure.
# ─────────────────────────────────────────────────────────────────────────────

import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("Audit")


def write_audit(
    db,
    type: str,
    action: str,
    subtype: Optional[str] = None,
    entity_id: Optional[int] = None,
    entity_name: Optional[str] = None,
    before: Optional[dict] = None,
    after: Optional[dict] = None,
    changed_by: str = "web_ui",
) -> None:
    """
    Insert one row into config_audit_log within an existing session.

    Must be called INSIDE an active `with get_db_session() as db:` block,
    BEFORE db.commit() — the audit row commits with the same transaction.

    Args:
        db          : Active SQLAlchemy session.
        type        : Top-level category. e.g. "indicator", "ai_prompt", "profile"
        action      : What happened. e.g. "create", "update", "delete", "toggle", "set_default"
        subtype     : Optional subcategory. e.g. "trend", "entry", "system"
        entity_id   : PK of the affected row (omit for deletes where you've already lost the id).
        entity_name : Human-readable label shown in the audit UI.
        before      : Dict snapshot of state BEFORE the change. None for creates.
        after       : Dict snapshot of state AFTER the change. None for deletes.
        changed_by  : Who triggered this. Defaults to "web_ui".
    """
    try:
        from db.models import ConfigAuditLog

        row = ConfigAuditLog(
            changed_at=datetime.now(timezone.utc),
            type=type,
            subtype=subtype,
            action=action,
            entity_id=entity_id,
            entity_name=entity_name,
            changed_by=changed_by,
            before=before,
            after=after,
        )
        db.add(row)
        # Deliberately NOT committing here — let the caller's transaction own the commit.
    except Exception as e:
        logger.error(f"Failed to write audit log entry: {e}", exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot helpers — call these BEFORE mutating a row to capture the "before"
# ─────────────────────────────────────────────────────────────────────────────

def snapshot_indicator(ind) -> dict:
    """Serialise an IndicatorDB row to a plain dict for audit storage."""
    return {
        "id":             ind.id,
        "profile_id":     ind.profile_id,
        "category":       ind.category,
        "indicator_type": ind.indicator_type,
        "params":         ind.params,
        "is_hard_stop":   ind.is_hard_stop,
        "enabled":        ind.enabled,
    }


def snapshot_ai_prompt(prompt) -> dict:
    """Serialise an AIPrompt row to a plain dict for audit storage."""
    return {
        "id":             prompt.id,
        "name":           prompt.name,
        "strategy_type":  prompt.strategy_type,
        "profile_id":     prompt.profile_id,
        "system_prompt":  prompt.system_prompt,
        "is_active":      prompt.is_active,
        "is_default":     prompt.is_default,
        "version":        prompt.version,
        "notes":          prompt.notes,
    }


def snapshot_profile(profile) -> dict:
    """Serialise key TradingProfileDB fields for audit storage."""
    return {
        "id":                        profile.id,
        "name":                      profile.name,
        "strategy_type":             profile.strategy_type,
        "take_profit_pct":           str(profile.take_profit_pct),
        "stop_loss_pct":             str(profile.stop_loss_pct),
        "trailing_stop_pct":         str(profile.trailing_stop_pct) if profile.trailing_stop_pct else None,
        "use_trailing_stop":         profile.use_trailing_stop,
        "min_signal_confidence":     profile.min_signal_confidence,
        "min_volume_ratio":          profile.min_volume_ratio,
        "min_indicators_required":   profile.min_indicators_required,
        "min_entry_indicators_required": profile.min_entry_indicators_required,
        "is_active":                 profile.is_active,
    }
