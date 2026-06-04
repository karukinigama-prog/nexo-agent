import socket
import psutil

_used_ports: dict[int, int] = {}  # port -> pid

def find_free_port(start: int = 8100, end: int = 8200) -> int:
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free ports available in range.")

def register_port(port: int, pid: int):
    _used_ports[port] = pid

def release_port(port: int):
    pid = _used_ports.pop(port, None)
    if pid:
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            proc.wait(timeout=3)
        except (psutil.NoSuchProcess, psutil.TimeoutExpired):
            pass
