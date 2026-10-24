from pathlib import Path
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

_REPO = Path(__file__).resolve().parents[3]
_UP = _REPO / "db" / "004_backend.sql"
_DOWN = _REPO / "db" / "004_backend.down.sql"

def _exec(path: Path) -> None:
    if not path.is_file(): raise RuntimeError(f"Не найден SQL-файл: {path}")
    bind = op.get_bind()
    sql = path.read_text(encoding="utf-8")
    from app.sql_utils import split_statements
    for stmt in split_statements(sql):
        if stmt.strip(): bind.exec_driver_sql(stmt)

def upgrade() -> None: _exec(_UP)
def downgrade() -> None: _exec(_DOWN)