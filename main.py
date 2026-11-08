"""
main.py - 부팅 자동 실행 (ESP32-S3)
===================================
ESP32 전원 인가 후 자동으로 메시 네트워크를 시작.
20초 카운트다운 후 espnow_mesh_pro.run() 실행.

카운트다운 중 REPL에서 Ctrl+C 로 중단 가능.
"""

import time


def main():
    print("=" * 50)
    print("  ESP32 Mesh Network Boot")
    print("=" * 50)
    print()
    print("20초 후 메시 네트워크가 시작됩니다.")
    print("중단하려면 Ctrl+C 를 누르세요.")
    print()

    for i in range(20, 0, -1):
        print("\r  {}초 후 시작...   ".format(i), end="")
        time.sleep(1)
    print("\r  시작!              ")
    print()

    import espnow_mesh_pro
    espnow_mesh_pro.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n부팅 대기 중단. REPL 모드로 진입.")
        print("수동 시작: import espnow_mesh_pro; espnow_mesh_pro.run()")
