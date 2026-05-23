"""Phase 2 — application engine.

Submodules:
  base_applier      shared abstract class + ApplyResult
  daily_limiter     enforces daily_application_limit
  captcha_detector  detects CAPTCHA + raises CaptchaDetected
  form_filler       generic form-field detector + filler
  screening_qa      Claude-on-Vertex answers to yes/no/short-text questions
  naukri_applier    Naukri quick apply
  applier_factory   resolve platform name -> applier instance
"""

from src.apply.base_applier import ApplyResult, ApplyStatus, BaseApplier
from src.apply.applier_factory import get_applier
from src.apply.daily_limiter import DailyLimiter

__all__ = [
    "ApplyResult",
    "ApplyStatus",
    "BaseApplier",
    "DailyLimiter",
    "get_applier",
]
