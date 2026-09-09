"""User-operated connection wizard. Never installs or starts remote software."""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import socket
import uuid
from .doctor import connection_guide


def endpoint(address, port='', mode='auto'):
    address = address.strip()
    # A single colon suffix is ambiguous in VNC viewers: ask rather than guess.
    if ':' in address:
        raise ValueError('请分别填写主机和 TCP 端口。VNC 的 :1 可能是显示编号，请向提供者确认实际端口。')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', address):
        raise ValueError('请填写域名或 IPv4 地址；暂不支持 IPv6。')
    if mode not in ('auto', 'ssh', 'vnc'):
        raise ValueError('连接方式应为 auto、ssh 或 vnc。')
    try:
        number = int(port) if str(port).strip() else {'ssh': 22, 'vnc': 5900}.get(mode)
    except ValueError:
        raise ValueError('端口必须是整数。') from None
    if number is None or not 1 <= number <= 65535:
        raise ValueError('请提供 1–65535 的实际 TCP 端口；自动识别不扫描端口。')
    return {'host': address, 'port': number, 'requested_transport': mode}


def detect(host, port):
    """Read only the greeting from one user-authorized endpoint; no credentials."""
    try:
        with socket.create_connection((host, port), timeout=4) as stream:
            stream.settimeout(4)
            banner = stream.recv(256)
        if banner.startswith(b'SSH-'):
            return 'ssh'
        if re.match(rb'RFB \d{3}\.\d{3}\n', banner):
            return 'vnc'
        return 'unknown'
    except OSError:
        return 'unreachable_or_no_greeting'


def store_password(reference, password):
    # No plaintext fallback and no arbitrary keyring backend invocation.
    try:
        import keyring
        backend = keyring.get_keyring()
        module = type(backend).__module__
        if module not in ('keyring.backends.Windows', 'keyring.backends.macOS', 'keyring.backends.SecretService'):
            raise RuntimeError('没有可用的系统安全凭据库。')
        backend.set_password('sentaurus-mcp', reference, password)
    except ImportError:
        raise RuntimeError('如需保存密码，请先安装本项目的 setup 可选依赖；密码未保存。') from None
    except Exception:
        raise RuntimeError('系统凭据库保存失败；密码未写入配置文件。') from None


def save_profile(path, profile):
    # Only known non-secret fields reach disk. Existing profiles are never overwritten.
    allowed = {'schema', 'host', 'port', 'requested_transport', 'detected_transport', 'username', 'auth', 'credential_ref', 'remote_python', 'remote_config', 'client_config', 'state'}
    if set(profile) - allowed:
        raise ValueError('Unexpected profile fields')
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(profile, stream, ensure_ascii=False, indent=2)


def load_profile(path):
    obj = json.loads(Path(path).expanduser().read_text(encoding='utf-8-sig'))
    if obj.get('schema') != 1:
        raise ValueError('Unsupported profile format')
    endpoint(obj.get('host', ''), obj.get('port', ''), obj.get('requested_transport', 'auto'))
    # Do not return unexpected data, passwords or stored client commands for execution.
    return {k: obj.get(k, '') for k in ('host', 'port', 'requested_transport', 'username', 'auth', 'remote_python', 'remote_config')}


def main():
    parser = argparse.ArgumentParser(description='本地连接向导 / local connection wizard')
    parser.add_argument('--gui', action='store_true', help='使用本机弹窗，不在 LLM 对话中输入密码')
    parser.add_argument('--load', help='仅读取指定的已有配置作为默认值，不扫描其他软件或凭据')
    parser.add_argument('--output', required=True, help='新配置 .txt 路径，不覆盖已有文件')
    args = parser.parse_args()
    root = None
    try:
        defaults = load_profile(args.load) if args.load else {}
        if args.gui:
            import tkinter as tk
            from tkinter import simpledialog, messagebox
            root = tk.Tk()
            root.withdraw()
            def ask(label, default='', secret=False):
                value = simpledialog.askstring('Sentaurus MCP 连接向导', label, initialvalue=str(default), show='*' if secret else None, parent=root)
                if value is None:
                    raise KeyboardInterrupt
                return value
            def show(text):
                messagebox.showinfo('Sentaurus MCP', text, parent=root)
        else:
            def ask(label, default='', secret=False):
                if secret:
                    return getpass.getpass(label + ': ')
                value = input(f'{label} [{default}]: ')
                return value or str(default)
            show = print
        def field(key, label, fallback=''):
            return ask(label, defaults.get(key) or fallback)
        mode = field('requested_transport', '连接方式：auto 不确定 / vnc / ssh', 'auto').strip().lower()
        host = field('host', '服务器域名或 IPv4（不要附带 :端口）')
        port = field('port', '实际 TCP 端口；VNC 显示编号不是端口', {'ssh': '22', 'vnc': '5900'}.get(mode, ''))
        profile = {'schema': 1, **endpoint(host, port, mode)}
        check = ask('是否只探测此地址和端口的协议握手？不登录、不扫描其他端口。yes/no', 'no')
        detected = detect(profile['host'], profile['port']) if check.lower() == 'yes' else 'not_checked'
        profile['detected_transport'] = detected
        transport = detected if detected in ('ssh', 'vnc') else mode
        if detected in ('ssh', 'vnc') and mode != 'auto' and detected != mode:
            show('检测协议与选择不一致，将按检测结果继续；这不代表认证成功。')
        if transport not in ('ssh', 'vnc'):
            show('未识别协议。请向管理员确认 SSH 或 VNC；不能只根据端口猜测。')
            profile['state'] = 'transport_unconfirmed'
        else:
            profile['username'] = field('username', 'Linux 用户名（VNC 可留空）')
            if transport == 'ssh' and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', profile['username']):
                raise ValueError('SSH 需要有效 Linux 用户名。')
            profile['auth'] = ask('认证方式：password / key / unknown', defaults.get('auth') or 'unknown').lower()
            if profile['auth'] not in ('password', 'key', 'unknown'):
                raise ValueError('认证方式无效。')
            if profile['auth'] == 'password':
                show('密码可选存入系统凭据库。当前版本不会自动使用该密码登录 VNC 或 SSH；SSH 后台执行仍需可用的非交互认证。')
                if ask('是否保存密码到本机系统凭据库？yes/no', 'no').lower() == 'yes':
                    if Path(args.output).expanduser().exists():
                        raise ValueError('输出文件已存在，请选择新文件名。')
                    password = ask('连接密码（隐藏输入，不发送给 LLM）', secret=True)
                    if password:
                        reference = str(uuid.uuid4())
                        store_password(reference, password)
                        profile['credential_ref'] = reference
                    password = None
            profile['state'] = 'saved_not_authenticated'
            if transport == 'ssh':
                profile['remote_python'] = field('remote_python', '服务器虚拟环境 Python 绝对路径（未知可留空）')
                profile['remote_config'] = field('remote_config', '服务器 MCP 配置绝对路径（未知可留空）')
                if profile['remote_python'] and profile['remote_config']:
                    guide = connection_guide('ssh', profile['host'], profile['username'], profile['port'], profile['remote_python'], profile['remote_config'])
                    profile['client_config'] = guide['client_config']
                else:
                    profile['state'] = 'server_deployment_details_missing'
            else:
                profile['state'] = 'vnc_saved_mcp_transport_unavailable'
                show('VNC 配置可保存，但本 MCP 不能通过 VNC 自动部署或执行仿真。需要另行提供 SSH，或在服务器本机运行客户端；不要把 VNC 密码当作 SSH 密码。')
        save_profile(args.output, profile)
        show('已保存本地配置：' + str(Path(args.output).expanduser().absolute()) + '\n不含明文密码；握手识别不等于认证成功或仿真可用。')
    except KeyboardInterrupt:
        print('已取消，未启动任何服务器任务。')
    except (ValueError, OSError, RuntimeError, ImportError) as exc:
        parser.exit(1, '向导未完成：' + str(exc) + '\n')
    finally:
        if root is not None:
            root.destroy()


if __name__ == '__main__':
    main()
