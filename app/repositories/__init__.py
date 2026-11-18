"""Repository layer — persistence only, no business rules.

Pattern — Repository:
  Services depend on these classes so SQLite can be swapped later
  without rewriting WeeklyFillService / AuthService.
"""

from app.repositories.credential_repository import CredentialRepository
from app.repositories.fill_run_repository import FillRunRepository
from app.repositories.schedule_repository import ScheduleRepository
from app.repositories.template_repository import TemplateRepository
from app.repositories.user_repository import UserRepository

__all__ = [
    "UserRepository",
    "CredentialRepository",
    "TemplateRepository",
    "ScheduleRepository",
    "FillRunRepository",
]
