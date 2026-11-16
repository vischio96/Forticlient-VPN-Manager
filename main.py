"""Entry point.

    FortiVPNManager.exe                         -> tray application
    FortiVPNManager.exe --connect-console NAME  -> interactive connection window (internal)
"""
import sys


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--connect-console":
        from fortivpn_manager import connect_console
        return connect_console.run(sys.argv[2])
    from fortivpn_manager import app
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
