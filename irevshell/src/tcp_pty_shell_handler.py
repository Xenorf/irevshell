# Built-in imports
import fcntl
import os
import select
import shutil
import socket
import termios

# External library imports
from loguru import logger

SWITCH_MODE_TRIGGER = b"\x18"
CONPTY_MODE_TRIGGER = b"\x10"


class PTY:
    """Represents a PTY

    Attributes:
        termios -- attributes of the current terminal.
        old_termios -- attributes of the terminal before execution.
        dumb_termios -- attributes fit for a dumb shell.
        interactive_termios -- attributes fit for an interactive shell.
        old_flags -- flags of the terminal before execution.
        shell_type -- mode of current terminal (dumb, interactive or conpty).
    """
    def __init__(self, slave=0, pid=os.getpid()):
        self.termios, self.fcntl = termios, fcntl
        self.shell_type = "interactive"

        self.pty = open(
            os.readlink("/proc/%d/fd/%d" % (pid, slave)), "r+b", buffering=0
        )

        self.old_termios = termios.tcgetattr(self.pty)
        self.interactive_termios = termios.tcgetattr(self.pty)
        self.dumb_termios = termios.tcgetattr(self.pty)

        self.interactive_termios[3] &= ~termios.ECHO & ~termios.ICANON
        for term in [self.interactive_termios, self.dumb_termios]:
            term[6][termios.VINTR] = 0 # ^C
            term[6][termios.VQUIT] = 0 # ^\
            term[6][termios.VSUSP] = 0 # ^Z

        self.old_flags = fcntl.fcntl(self.pty, fcntl.F_GETFL)

    def switch_terminal_mode(self):
        """Change the mode of the terminal by modifying the flags and attributes according to the shell_type attribute."""
        if self.shell_type == "interactive":
            logger.info(
                "Switching to interactive mode, make sure your shell has a tty."
            )
            termios.tcsetattr(self.pty, termios.TCSADRAIN, self.interactive_termios)
            # fcntl.fcntl(self.pty, fcntl.F_SETFD, fcntl.FD_CLOEXEC)
            # fcntl.fcntl(self.pty, fcntl.F_SETFL, self.old_flags | os.O_NONBLOCK)
        elif self.shell_type == "dumb":
            logger.info(
                "Switching to dumb mode, perfect if you don't have a tty."
            )
            termios.tcsetattr(self.pty, termios.TCSADRAIN, self.dumb_termios)
            # fcntl.fcntl(self.pty, fcntl.F_SETFL, self.old_flags | os.O_NONBLOCK)
            # fcntl.fcntl(self.pty, self.fcntl.F_SETFL, self.old_flags)
        else:
            logger.info("Switching to ConPty mode. This won't work with a Linux shell.")
            termios.tcsetattr(self.pty, termios.TCSADRAIN, self.interactive_termios)

    def read(self, size=8192):
        return self.pty.read(size)

    def write(self, data):
        ret = self.pty.write(data)
        self.pty.flush()
        return ret

    def fileno(self):
        return self.pty.fileno()

    def __del__(self):
        """Restore the terminal settings on deletion."""
        self.termios.tcsetattr(self.pty, self.termios.TCSAFLUSH, self.old_termios)
        self.fcntl.fcntl(self.pty, self.fcntl.F_SETFL, self.old_flags)


class Shell:
    """Represents a shell 

    Attributes:
        bind -- boolean setting the shell into listening or bind mode.
        address -- IP address and port tuple used to setup the connection.
        conpty -- boolean used to make the listener compatible with ConPtyShell.
        size -- string representing the number of rows and columns with a space separator.
    """
    def __init__(self, address, conpty, bind):
        self.bind = bind
        self.address = address
        self.conpty = conpty
        self.size = self.get_terminal_size()

        if not self.bind:
            self.sock = socket.socket()
            try:
                self.sock.bind(self.address)
                self.sock.listen(5)
            except OSError as e:
                logger.critical(f"{e}")
                exit(1)

    def get_terminal_size(self):
        """Return the terminal dimensions (rows columns)"""
        size = shutil.get_terminal_size()
        return f"{size.lines} {size.columns}"

    def handle(self):
        """Setup the connection, the PTY and handle I/O from shell"""
        if self.bind:
            connection = socket.socket()
            try:
                connection.connect(self.address)
            except ConnectionRefusedError:
                logger.critical(f"Connection refused to {self.address}")
                exit(1)
            logger.info(f"Connected to {self.address}")
        else:
            logger.info(f"Terminal size are {self.size}.")
            logger.info(f"Waiting for incoming connection on {self.address}.")
            connection, address = self.sock.accept()
            if self.conpty:
                connection.send(self.size.encode())
            logger.info(f"Connection accepted from {address}")

        pty = PTY()

        buffers = [[connection, []], [pty, []]]

        def buffer_index(fd):
            for index, buffer in enumerate(buffers):
                if buffer[0] == fd:
                    return index

        readable_fds = [connection, pty]
        r, _, _ = select.select(readable_fds, [], [], 0.3)
        if r or self.conpty:
            pty.switch_terminal_mode()
        else:
            pty.shell_type = "dumb"
            pty.switch_terminal_mode()

        data = " "
        command_buffer = data
        try:
            while data:
                writable_fds = []
                for buffer in buffers:
                    if buffer[1]:
                        writable_fds.append(buffer[0])

                r, w, _ = select.select(readable_fds, writable_fds, [])

                for fd in r:
                    buffer = buffers[buffer_index(fd) ^ 1][1]
                    if hasattr(fd, "read"):
                        data = fd.read(8192)

                        command_buffer += data.decode(errors="ignore")
                        # Check if user pressed Enter (i.e., full command entered)
                        if "\n" in command_buffer:
                            full_command, command_buffer = command_buffer.split("\n", 1)
                            logger.log("COMMAND", f"{full_command.strip()}")
                    else:
                        data = fd.recv(8192)
                    if data:
                        buffer.append(data)

                for fd in w:
                    buffer = buffers[buffer_index(fd)][1]
                    data = buffer[0]

                    if data.strip() == SWITCH_MODE_TRIGGER:
                        self.conpty = False
                        pty.shell_type = (
                            "interactive" if pty.shell_type == "dumb" else "dumb"
                        )
                        pty.switch_terminal_mode()
                    elif data.strip() == CONPTY_MODE_TRIGGER:
                        pty.shell_type = "interactive" if self.conpty else "conpty"
                        self.conpty = not self.conpty
                        pty.switch_terminal_mode()
                    else:
                        if hasattr(fd, "write"):
                            fd.write(data)
                        else:
                            if self.conpty:
                                fd.send(data.replace(b"\n", b"\r"))
                            else:
                                fd.send(data)
                    buffer.remove(data)
        except ConnectionResetError as e:
            logger.debug(f"{e}")
        finally:
            logger.info(
                f"Connection closed from {self.address}, press CTRL+C to exit gracefully"
            )
            if connection:
                connection.close()
            if self.bind:
                exit(0)
