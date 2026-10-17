"""The one place that decides which repository the app uses.

Swap to a PostgreSQL-backed repository here later.
"""
from .repository import InMemoryRepository
from .seed import seed

repo = InMemoryRepository()
seed(repo)
