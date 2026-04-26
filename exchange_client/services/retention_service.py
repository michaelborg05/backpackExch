# services/retention_service.py
from utils.logging import log_manager
from utils.settings_helper import get_settings_helper
from db.utils import get_db_session
from db.crud_retention import run_all_retention


class RetentionService:
    """Runs nightly data retention policies against all configured tables."""

    def __init__(self):
        self.logger = log_manager.get_logger("RetentionService")
        self.settings = get_settings_helper()

    def run(self) -> dict:
        """
        Execute all retention deletes. Returns a dict of {table: rows_deleted}.
        Safe to call multiple times; only deletes rows beyond the configured age.
        """
        tx_days = self.settings.retention_trans_history_days
        trend_days = self.settings.retention_trenddata_history_days
        audit_days = self.settings.retention_audit_history_days

        self.logger.info(
            f"Running retention: transaction={tx_days}d, "
            f"trend={trend_days}d, audit={audit_days}d"
        )

        try:
            with get_db_session() as db:
                results = run_all_retention(
                    db,
                    retention_trans_history_days=tx_days,
                    retention_trenddata_history_days=trend_days,
                    retention_audit_history_days=audit_days,
                )

            total = sum(results.values())
            self.logger.info(
                f"Retention complete — {total} rows deleted: "
                + ", ".join(f"{t}={n}" for t, n in results.items())
            )
            return results

        except Exception as e:
            self.logger.error(f"Retention run failed: {e}", exc_info=True)
            return {}


_retention_service: RetentionService | None = None


def get_retention_service() -> RetentionService:
    global _retention_service
    if _retention_service is None:
        _retention_service = RetentionService()
    return _retention_service
