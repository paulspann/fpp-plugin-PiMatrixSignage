from pathlib import Path
import ast
import builtins

ROOT = Path(__file__).resolve().parents[1]


def test_v063_all_named_route_decorators_exist_before_use():
    # Route decorators execute while app.py is imported. v0.6.2 reached
    # @login_required before any such symbol existed and systemd crashed with
    # NameError. Walk the module in source order and ensure every simple named
    # decorator has already been imported/assigned/defined when it is used.
    source = (ROOT / 'app.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    available = set(dir(builtins))

    for node in tree.body:
        decorators = getattr(node, 'decorator_list', [])
        for dec in decorators:
            for name_node in ast.walk(dec):
                if isinstance(name_node, ast.Name) and name_node.id not in available:
                    # Attribute roots such as app in @app.get are validated by
                    # the same rule; call arguments are constants in app.py.
                    raise AssertionError(
                        f"Decorator name {name_node.id!r} is unavailable before line {node.lineno}"
                    )

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            available.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                available.add(alias.asname or alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                available.add(alias.asname or alias.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    available.add(target.id)


def test_v063_license_status_route_uses_global_authentication_gate():
    source = (ROOT / 'app.py').read_text(encoding='utf-8')
    assert '@app.get("/api/license")\ndef license_status_api():' in source
    assert '@login_required' not in source
    assert 'def require_login_and_csrf():' in source


def test_release_version_is_v063_or_later():
    version = tuple(int(x) for x in (ROOT / 'VERSION').read_text(encoding='utf-8').strip().split('.')[:3])
    assert version >= (0, 6, 3)
