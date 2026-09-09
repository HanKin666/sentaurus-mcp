import json
import socket
import threading
import pytest
from sentaurus_mcp.setup import endpoint, detect, save_profile, load_profile, main


def test_endpoint_ambiguity():
    with pytest.raises(ValueError):
        endpoint('server:01', '', 'vnc')
    with pytest.raises(ValueError):
        endpoint('server', '', 'auto')
    assert endpoint('server', '2222', 'ssh')['port'] == 2222


def test_banner_only():
    with socket.socket() as server:
        server.bind(('127.0.0.1', 0))
        server.listen()
        def reply():
            conn, _ = server.accept()
            with conn:
                conn.sendall(b'RFB 003.008\n')
        thread = threading.Thread(target=reply)
        thread.start()
        assert detect('127.0.0.1', server.getsockname()[1]) == 'vnc'
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_profile_no_secrets_no_overwrite(tmp_path):
    path = tmp_path/'connection.txt'
    data = {'schema': 1, **endpoint('example.com', 22, 'ssh'), 'username': 'user'}
    with pytest.raises(ValueError):
        save_profile(path, {**data, 'password': 'secret'})
    assert not path.exists()
    save_profile(path, data)
    assert load_profile(path)['host'] == 'example.com'
    with pytest.raises(FileExistsError):
        save_profile(path, data)


def test_vnc_wizard(tmp_path, monkeypatch):
    path = tmp_path/'connection.txt'
    answers = iter(['vnc', 'server.example.com', '5901', 'no', '', 'password', 'no'])
    monkeypatch.setattr('builtins.input', lambda _: next(answers))
    monkeypatch.setattr('sys.argv', ['setup', '--output', str(path)])
    main()
    data = json.loads(path.read_text(encoding='utf-8'))
    assert data['state'] == 'vnc_saved_mcp_transport_unavailable'
    assert 'credential_ref' not in data
