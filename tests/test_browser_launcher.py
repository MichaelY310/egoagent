"""Browser entry tests do not invoke a real browser, model or editor."""
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest

from desktop import browser_launcher as browser


def test_plain_url_preserves_default_browser_workspace_choice():
    assert browser.browser_url('http://127.0.0.1:8880') == 'http://127.0.0.1:8880/'


@pytest.mark.parametrize('origin', ['https://example.com', 'file:///C:/x', 'http://user@localhost:8880',
                                    'http://localhost:8880/?x=1', 'http://localhost:8880/untrusted'])
def test_rejects_nonlocal_or_nonorigin_url(origin):
    with pytest.raises(ValueError, match='local EgoAgent'):
        browser.browser_url(origin)


def test_folder_url_is_encoded_and_cannot_add_query_arguments(tmp_path):
    folder = tmp_path / '项目 with spaces & text'
    folder.mkdir()
    url = browser.browser_url('http://localhost:8880/', folder)
    params = parse_qs(urlsplit(url).query)
    assert set(params) == {'folder'}
    assert params['folder'][0].endswith('/项目 with spaces & text')


@pytest.mark.parametrize('started', [True, False])
def test_starts_or_reuses_before_opening_browser(tmp_path, started):
    order = []
    def ensure(root, ports):
        assert root == tmp_path
        order.append('healthy')
        return {'ok': True, 'origin': 'http://127.0.0.1:8880', 'started': started}
    with patch.object(browser, 'load_local_env'), patch.object(browser, 'runtime_ports', return_value={'LISTEN': 8880}), \
            patch.object(browser.bootstrap, 'ensure_services', side_effect=ensure), \
            patch.object(browser.os, 'startfile', create=True, side_effect=lambda _: order.append('browser')) as open_browser:
        result = browser.launch(tmp_path)
    assert order == ['healthy', 'browser']
    assert result['started'] is started
    open_browser.assert_called_once_with('http://127.0.0.1:8880/')


def test_failed_start_never_opens_browser(tmp_path):
    with patch.object(browser, 'load_local_env'), \
            patch.object(browser.bootstrap, 'ensure_services', side_effect=RuntimeError('port occupied')), \
            patch.object(browser.os, 'startfile', create=True) as open_browser:
        with pytest.raises(RuntimeError, match='port occupied'):
            browser.launch(tmp_path)
        open_browser.assert_not_called()


def test_invalid_workspace_does_not_start_services(tmp_path):
    with patch.object(browser.bootstrap, 'ensure_services') as start:
        with pytest.raises(FileNotFoundError):
            browser.launch(tmp_path, tmp_path / 'missing')
        start.assert_not_called()


def test_windowless_errors_are_visible_and_logged(tmp_path):
    with patch.object(browser, 'ROOT', tmp_path), patch.object(browser, 'launch', side_effect=RuntimeError('test error')), \
            patch.object(browser, 'report_failure') as notify:
        assert browser.main([]) == 1
    log = tmp_path / '.runtime/desktop/browser-launcher.log'
    assert 'test error' in log.read_text(encoding='utf-8')
    notify.assert_called_once_with('test error', log)


def test_shortcut_uses_pythonw_not_desktop_executable():
    source = (Path(__file__).resolve().parents[1] / 'desktop/install-browser.ps1').read_text(encoding='utf-8')
    assert 'pythonw.exe' in source and 'browser_launcher.py' in source
    assert 'EgoAgent.exe' not in source
    assert 'already belongs to another installation' in source
