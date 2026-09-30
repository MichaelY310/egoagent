"""Exercise the launcher supervisor without importing or starting the app."""
import ast
from pathlib import Path
from unittest.mock import Mock


def supervisor_namespace():
    source = Path(__file__).resolve().parents[1] / 'start-all.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_supervise_backend')
    namespace = {'BACKEND_PORT': 8765, '_port_is_open': Mock(return_value=False),
                 '_stop_owned_process': Mock(), 'start_backend_if_needed': Mock(), 'print': Mock()}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
    return namespace


def test_busy_living_backend_is_never_killed_by_tcp_probe():
    ns = supervisor_namespace()
    process = Mock()
    process.poll.return_value = None
    stop = Mock()
    stop.wait.side_effect = [False, False, False, True]
    ns['_supervise_backend']({'process': process}, stop)
    ns['_stop_owned_process'].assert_not_called()
    ns['start_backend_if_needed'].assert_not_called()


def test_dead_backend_is_restarted_but_existing_unowned_service_is_not():
    ns = supervisor_namespace()
    process = Mock()
    process.poll.return_value = 1
    stop = Mock()
    stop.wait.side_effect = [False, True]
    holder = {'process': process}
    ns['_supervise_backend'](holder, stop)
    ns['start_backend_if_needed'].assert_called_once()
    assert holder['process'] is ns['start_backend_if_needed'].return_value
    ns = supervisor_namespace()
    ns['_port_is_open'].return_value = True
    stop.wait.side_effect = [False, True]
    ns['_supervise_backend']({'process': None}, stop)
    ns['start_backend_if_needed'].assert_not_called()
