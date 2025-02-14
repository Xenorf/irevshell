# Built-in imports
import argparse
import ipaddress
import sys

# External library imports
from loguru import logger

# Local imports
from irevshell.src.tcp_pty_shell_handler import Shell


def validate_ip(ip_str):
    """Validate and return an IP address."""
    try:
        return ipaddress.ip_address(ip_str)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid IP address: '{ip_str}'")


def validate_port(port_str):
    """Validate and return a port number."""
    port = int(port_str)
    if 1 <= port <= 65535:
        return port
    else:
        raise argparse.ArgumentTypeError(
            f"Invalid port number: '{port_str}'. Must be an integer between 1 and 65535."
        )


def set_log_level(level, output_file):
    """Sets the log level and log file.

    Args:
        level -- the log level to display (default "info")
        output_file -- the file used to output logs, including commands
    """
    logger.level("COMMAND", no=15)
    if level.upper() != "NONE":
        LOG_FORMAT = "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <level>{message}</level>"
        logger.remove()  # Remove any default handlers
        logger.add(sys.stderr, format=LOG_FORMAT, level=level.upper())
        try:
            logger.add(
                output_file,
                rotation="10 MB",
                retention="30 days",
                level="COMMAND" if level.upper() != "DEBUG" else "DEBUG",
                format=LOG_FORMAT,
            )
        except PermissionError:
            logger.critical(
                f"Permission denied to write to {output_file}, continuing without logs"
            )
        logger.debug(f"Logger initialized to {level.upper()}")


@logger.catch
def run() -> None:
    """Handle arguments and setup."""
    parser = argparse.ArgumentParser(
        prog="irevshell",
        description="Simple reverse shell listener aimed at professionnals who want an almost built-in interactivity and systematic logging.",
        add_help=True,
    )

    parser.add_argument(
        "--ip",
        "-i",
        type=validate_ip,
        default="0.0.0.0",
        help="Listening address.",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=validate_port,
        default="4444",
        help="Listening port.",
    )
    parser.add_argument(
        "--bind",
        default=False,
        action="store_true",
        help="Bind mode, used to connect to a remote listener.",
    )
    parser.add_argument(
        "--conpty",
        "-c",
        action="store_true",
        help="Mode to support antonioCoco/ConPtyShell",
    )
    parser.add_argument(
        "--log-level",
        "-l",
        choices=["none", "debug", "info", "warning", "error", "critical"],
        default="info",
        help="Level of debug you wish to display.",
    )
    parser.add_argument(
        "--log-filename",
        "-o",
        default="reverse.log",
        help="Output file used to store logs",
    )
    args = parser.parse_args()

    listening_address = (str(args.ip), args.port)
    log_level = args.log_level
    log_filename = args.log_filename
    conpty = args.conpty
    bind = args.bind

    set_log_level(log_level, log_filename)
    l = Shell(listening_address, conpty, bind)

    while True:
        try:
            l.handle()
        except KeyboardInterrupt:
            logger.info(f"Exiting gracefully.")
            break
