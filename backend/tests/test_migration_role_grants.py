"""ترحيل بيـGRANT لدور مش موجود بيسقط الـupgrade كله.

`sales_app` بيتعمل في `scripts/provision.py`، والترتيب بينه وبين Alembic مش ثابت: في الإنتاج
الدور موجود قبل الترحيل، وفي قاعدة CI بيتعمل بعده أو مش موجود خالص. أي `GRANT ... TO sales_app`
بره حارس `pg_roles` بيرمي `role "sales_app" does not exist` ويوقف كل الترحيلات اللي بعده، وده
اللي حصل فعلاً في CI run 46087084159 (job live-api، خطوة Apply migrations).

التست ده بيفحص كل ملفات الترحيل: كل GRANT للدور لازم يكون جوه DO block بيتأكد من `pg_roles`،
وكل GRANT للدور لازم يظهر مرتين على الأقل في الملف (شرط الوجود + الجرانت نفسه).
"""

from __future__ import annotations

import ast
import pathlib
import re

VERSIONS = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "versions"
GRANT_TO_APP = re.compile(r"\bGRANT\b[^;]*?\bTO\s+sales_app\b", re.IGNORECASE | re.DOTALL)


def _executed_sql(path: pathlib.Path) -> list[str]:
    """كل نص SQL بيتبعت لـ``op.execute`` كـliteral، من غير الشرح اللي في الـdocstrings.

    الفحص على النص الخام بيخلط الكلام اللي في التوثيق بكود الترحيل (الشرح بيذكر
    ``GRANT ... TO sales_app`` كمثال)، فالتحليل على شجرة الـAST بيفصل التنفيذ عن الشرح.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    statements: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "execute" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            statements.append(first.value)
        elif isinstance(first, ast.JoinedStr):
            # f-string: القيم المتغيّرة بتتحول لـ{} والقوالب النصية بتفضل، فالـGRANT اللي بيتكتب
            # بأسماء جداول متغيّرة بيتفحص زي اللي مكتوب بالنص.
            statements.append(
                "".join(
                    part.value
                    if isinstance(part, ast.Constant) and isinstance(part.value, str)
                    else "{}"
                    for part in first.values
                )
            )
    return statements


def _unguarded_grants(sql: str) -> list[str]:
    """الـGRANT اللي مش متحوّط بحارس ``pg_roles`` جوه نفس الجملة."""
    offenders: list[str] = []
    for match in GRANT_TO_APP.finditer(sql):
        statement = match.group(0).strip()
        window = sql[: match.end()]
        if "pg_roles" not in window:
            offenders.append(statement)
    return offenders


def _executed_sql_str(source: str) -> list[str]:
    """نفس `_executed_sql` بس على نص، عشان التست يثبت إن الشرح مش SQL."""
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        name = handle.name
    try:
        return _executed_sql(pathlib.Path(name))
    finally:
        pathlib.Path(name).unlink()


class TestEveryRoleGrantIsGuarded:
    def test_no_migration_grants_to_the_runtime_role_without_a_role_check(self) -> None:
        offenders: list[str] = []
        for path in sorted(VERSIONS.glob("*.py")):
            for statement in _executed_sql(path):
                for grant in _unguarded_grants(statement):
                    offenders.append(f"{path.name}: {grant}")
        assert offenders == [], "GRANT بلا حارس pg_roles:\n" + "\n".join(offenders)

    def test_the_guard_is_what_makes_the_missing_role_case_pass(self) -> None:
        # النسخة اللي كسرت live-api: جرانت مكشوف.
        broken = "GRANT SELECT, INSERT, UPDATE, DELETE ON workspace_memberships TO sales_app"
        assert _unguarded_grants(broken) == [broken]
        # والنسخة المصلحة بتعدي.
        fixed = (
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON workspace_memberships TO sales_app; "
            "END IF; END $$;"
        )
        assert _unguarded_grants(fixed) == []

    def test_prose_in_a_docstring_is_not_mistaken_for_a_grant(self) -> None:
        prose = (
            '"""It used to run GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public '
            'TO sales_app."""\n'
            "def upgrade():\n"
            "    pass\n"
        )
        assert _executed_sql_str(prose) == []

    def test_the_workspace_membership_migration_itself_is_guarded(self) -> None:
        statements = _executed_sql(VERSIONS / "fe2026112705_workspace_memberships.py")
        grants = [s for s in statements if "TO sales_app" in s]
        assert len(grants) == 1
        assert "pg_roles" in grants[0]
        assert _unguarded_grants(grants[0]) == []
