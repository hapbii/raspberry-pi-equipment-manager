from __future__ import annotations

import socket


def local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 80))
        return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        sock.close()


if __name__ == "__main__":
    address = local_ip()
    print("기자재 관리 시스템 접속 주소")
    print(f"- 이 장치: http://127.0.0.1:8080")
    print(f"- 학교 내부망: http://{address}:8080")
    print("다른 교실과 다른 Wi-Fi에서도 두 번째 주소로 접속 시험을 진행하세요.")
