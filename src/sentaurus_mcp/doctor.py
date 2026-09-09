"""Read-only readiness checks and explicit remote deployment guidance."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time


def diagnose(config_path=None):
    report = {'runtime': {'state': 'available', 'platform': sys.platform},
              'connection': {'state': 'current_host_only', 'message': '仅检查当前 MCP 所在主机，不代表已连接远程服务器。'},
              'configuration': {'state': 'missing'}, 'storage': {'state': 'unknown'},
              'worker': {'state': 'unknown'}, 'tools': {},
              'license': {'state': 'unverified', 'message': '文件存在不代表许可证有效或仿真可运行。'},
              'actions_enabled': os.getenv('SENTAURUS_ENABLE_ACTIONS', '0') == '1',
              'next_steps': []}
    value = config_path or os.getenv('SENTAURUS_MCP_CONFIG')
    if not value:
        report['next_steps'].append('设置 SENTAURUS_MCP_CONFIG，指向当前主机上的配置文件；远程服务器须先部署。')
        return report
    try:
        config = json.loads(Path(value).read_text(encoding='utf-8-sig'))
        root = Path(config['root'])
        if not root.is_absolute():
            raise ValueError('root must be absolute')
        profiles = config.get('tools', {})
        if not isinstance(profiles, dict):
            raise ValueError('tools must be an object')
    except (OSError, ValueError, KeyError, TypeError):
        report['configuration']['state'] = 'invalid'
        report['next_steps'].append('检查配置文件可读、JSON 格式以及 root 绝对路径。')
        return report
    report['configuration']['state'] = 'valid'
    report['storage']['state'] = 'accessible' if root.is_dir() and os.access(root, os.W_OK | os.X_OK) else 'not_ready'
    report['storage']['message'] = '权限检查不创建文件；实际写入仍需验证。'
    for name, argv in profiles.items():
        valid = isinstance(argv, list) and bool(argv) and all(isinstance(x, str) for x in argv)
        executable = Path(argv[0]) if valid else None
        ready = valid and executable.is_absolute() and executable.is_file() and os.access(executable, os.X_OK)
        report['tools'][name] = {'state': 'executable_found' if ready else 'not_found', 'execution': 'unverified'}
    if not profiles or any(v['state'] != 'executable_found' for v in report['tools'].values()):
        report['next_steps'].append('在运行主机配置真实 Sentaurus 可执行文件路径。')
    dbpath = root / 'experiments.sqlite3'
    if not dbpath.is_file():
        report['worker']['state'] = 'offline'
    else:
        try:
            with sqlite3.connect(dbpath.resolve().as_uri() + '?mode=ro', uri=True, timeout=2) as db:
                row = db.execute('SELECT heartbeat FROM worker WHERE id=1').fetchone()
            age = time.time() - float(row[0]) if row else None
            report['worker'] = {'state': 'online' if age is not None and 0 <= age <= 10 else 'stale_or_offline', 'heartbeat_age_seconds': age}
        except (sqlite3.Error, ValueError, TypeError):
            report['worker']['state'] = 'unreadable'
    if report['worker']['state'] != 'online':
        report['next_steps'].append('在服务器独立终端或服务管理器启动 sentaurus-worker，并使用同一配置。')
    if report['storage']['state'] != 'accessible':
        report['next_steps'].append('由操作员准备可写数据目录；本检查不会自动创建目录。')
    report['next_steps'].append('用已审查的小型实验验证真实执行与许可证；不要把诊断通过当作物理验收。')
    return report


def connection_guide(mode='ssh', host='', user='', port=22, remote_python='', remote_config=''):
    if mode == 'vnc':
        return {'state': 'unsupported_transport', 'message': 'VNC 仅提供桌面画面，当前 MCP 不支持通过 VNC 自动部署或传输工具调用。',
                'steps': ['向管理员申请 SSH 或其他获准的通信方式。', '可在服务器桌面手动安装 MCP，并独立启动执行器。', '仅启动代理不够；本机客户端仍需可用的 SSH 通道，或在服务器本机运行客户端。']}
    if mode != 'ssh':
        raise ValueError('mode must be ssh or vnc')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', host) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', user):
        raise ValueError('Provide a hostname/IPv4 address and Linux username; IPv6 is not supported by this guide yet')
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError('Invalid SSH port')
    for path in (remote_python, remote_config):
        if not path.startswith('/') or any(c in path for c in '\n\r\x00'):
            raise ValueError('Provide absolute server-side paths')
    prefix = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10', '-p', str(port), user + '@' + host]
    remote = shlex.join(['env', 'SENTAURUS_MCP_CONFIG=' + remote_config, 'SENTAURUS_ENABLE_ACTIONS=0', remote_python, '-m', 'sentaurus_mcp.server'])
    return {'state': 'not_tested', 'client_config': {'mcpServers': {'sentaurus': {'command': 'ssh', 'args': prefix[1:] + [remote]}}},
            'probe_argv': prefix + [shlex.join([remote_python, '-m', 'sentaurus_mcp.doctor', '--config', remote_config])],
            'steps': ['先核对 SSH 主机指纹并在本机准备认证；不会弹出密码框，也不接收密码。', '在服务器虚拟环境安装本项目，配置软件路径及许可证环境。', '独立启动服务器执行器；再运行显式 SSH 检查。', '将生成的只读配置填入兼容客户端；需提交实验时自行改为写入模式。']}


def main():
    parser = argparse.ArgumentParser(description='Sentaurus MCP 连接诊断 / connection diagnostics')
    parser.add_argument('--config')
    parser.add_argument('--mode', choices=['local', 'ssh', 'vnc'], default='local')
    parser.add_argument('--host', default='')
    parser.add_argument('--user', default='')
    parser.add_argument('--port', type=int, default=22)
    parser.add_argument('--remote-python', default='')
    parser.add_argument('--remote-config', default='')
    parser.add_argument('--probe', action='store_true', help='显式通过 SSH 执行远程只读诊断；不部署、不启动仿真')
    args = parser.parse_args()
    try:
        if args.mode == 'local':
            result = diagnose(args.config)
        else:
            result = connection_guide(args.mode, args.host, args.user, args.port, args.remote_python, args.remote_config)
            if args.probe and args.mode == 'ssh':
                if not shutil.which('ssh'):
                    result['probe'] = {'state': 'ssh_client_missing'}
                else:
                    try:
                        proc = subprocess.run(result['probe_argv'], capture_output=True, text=True, timeout=30)
                        if proc.returncode == 0:
                            remote = json.loads(proc.stdout)
                            if not isinstance(remote, dict) or not all(k in remote for k in ('runtime', 'worker', 'configuration')):
                                raise ValueError('Invalid diagnostic response')
                            result['probe'] = {'state': 'remote_diagnostic_received', 'report': remote}
                        else:
                            result['probe'] = {'state': 'failed', 'exit_code': proc.returncode, 'message': '检查认证、主机密钥、远程 Python/包路径；可在本机终端手动检查，不要发送密码。'}
                    except subprocess.TimeoutExpired:
                        result['probe'] = {'state': 'connection_check_timeout', 'message': '仅连接检查超时，不代表仿真超时。'}
                    except (ValueError, OSError):
                        result['probe'] = {'state': 'invalid_response_or_launch_error'}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
