"""Daemon entry point script."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .daemon import TaskDaemon
from .transport import TransportType


def setup_logging():
    """Setup logging for daemon."""
    # Configure logging to file
    log_dir = Path.home() / ".exobrain" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "task-daemon.log"

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
    )

    logger = logging.getLogger(__name__)
    logger.info(f"Logging to: {log_file}")
    return logger


def main():
    """Main entry point for daemon."""
    # Setup logging first
    logger = setup_logging()
    logger.info("Starting daemon runner")

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Task daemon process")
    parser.add_argument(
        "--storage-path", default="~/.exobrain/data/tasks", help="Path to task storage directory"
    )
    parser.add_argument(
        "--transport",
        choices=["auto", "unix", "pipe", "http"],
        default="auto",
        help="Transport type to use",
    )
    parser.add_argument("--socket-path", help="Unix socket path (for unix transport)")
    parser.add_argument("--pipe-name", help="Named pipe name (for pipe transport)")
    parser.add_argument("--host", help="HTTP host (for http transport)")
    parser.add_argument("--port", type=int, help="HTTP port (for http transport)")
    parser.add_argument(
        "--pid-file", default="~/.exobrain/task-daemon.pid", help="Path to PID file"
    )

    args = parser.parse_args()

    # Build transport config
    transport_config = {}
    if args.socket_path:
        transport_config["socket_path"] = args.socket_path
    if args.pipe_name:
        transport_config["pipe_name"] = args.pipe_name
    if args.host:
        transport_config["host"] = args.host
    if args.port:
        transport_config["port"] = args.port

    # Convert transport type
    transport_type = TransportType(args.transport)

    # Check if daemon is already running
    if TaskDaemon.is_running(args.pid_file):
        print("Task daemon is already running")
        sys.exit(1)

    # Create daemon
    daemon = TaskDaemon(
        storage_path=args.storage_path,
        transport_type=transport_type,
        transport_config=transport_config,
        pid_file=args.pid_file,
    )

    # Run daemon
    async def run_daemon():
        """Run daemon with proper async context."""
        await daemon.start()
        await daemon.run()

    try:
        asyncio.run(run_daemon())
    except KeyboardInterrupt:
        print("\nShutting down daemon...")
    except Exception as e:
        print(f"Error running daemon: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
