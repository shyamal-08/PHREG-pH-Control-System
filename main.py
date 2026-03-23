"""Entry point for modular PHREG controller.

Run from project root:
    python -m controller.main --log_enable
"""

from controller.controller import PHREGController


def main():
    PHREGController().run()


if __name__ == "__main__":
    main()
