import argparse
import sys
import yaml
from datetime import datetime, timedelta, timezone
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from datetime import datetime, timezone, timedelta
#from profile_variants  import RANGE_VARIANTS, MEAN_REV_VARIANTS, run_all_variants
from backtesting.profile_variants import RANGE_VARIANTS, MEAN_REV_VARIANTS, run_all_variants
from db.utils import get_db_session

end   = datetime.now(tz=timezone.utc)
start = end - timedelta(days=7)  # Use 7 days for meaningful sample

with get_db_session() as db:
    # Test range variants on SOL
    print("=== RANGE TRADING - SOL ===")
    run_all_variants(db, "SOL_USDC", start, end, RANGE_VARIANTS)

    # Test mean reversion variants on SUI
    print("\n=== MEAN REVERSION - SUI ===")
    run_all_variants(db, "SUI_USDC", start, end, MEAN_REV_VARIANTS)