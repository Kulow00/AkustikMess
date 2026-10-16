"""Minimaler SFTP-Server für Tests (paramiko), bildet einen lokalen Ordner ab."""

import os
import socket
import threading

import paramiko


class _Auth(paramiko.ServerInterface):
    def __init__(self, user, allowed_key_b64):
        self.user, self.allowed = user, allowed_key_b64

    def check_auth_publickey(self, username, key):
        ok = username == self.user and key.get_base64() == self.allowed
        return paramiko.AUTH_SUCCESSFUL if ok else paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "publickey"

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED


class _Handle(paramiko.SFTPHandle):
    def stat(self):
        return paramiko.SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))


def make_sftp_server_class(root, events):
    class _SFTP(paramiko.SFTPServerInterface):
        def _p(self, path):
            return os.path.join(root, path.lstrip("/").replace("/", os.sep))

        def stat(self, path):
            try:
                return paramiko.SFTPAttributes.from_stat(os.stat(self._p(path)))
            except OSError as e:
                return paramiko.SFTPServer.convert_errno(e.errno)

        lstat = stat

        def list_folder(self, path):
            p = self._p(path)
            return [paramiko.SFTPAttributes.from_stat(os.stat(os.path.join(p, n)), n) for n in os.listdir(p)]

        def open(self, path, flags, attr):
            p = self._p(path)
            try:
                fd = os.open(p, flags | getattr(os, "O_BINARY", 0), 0o644)
            except OSError as e:
                return paramiko.SFTPServer.convert_errno(e.errno)
            mode = "wb" if flags & os.O_WRONLY else "r+b" if flags & os.O_RDWR else "rb"
            if flags & os.O_APPEND:
                mode = "ab"
            f = os.fdopen(fd, mode)
            h = _Handle(flags)
            h.filename = p
            h.readfile = h.writefile = f
            return h

        def remove(self, path):
            os.remove(self._p(path))
            events.append(("remove", path))
            return paramiko.SFTP_OK

        def rename(self, old, new):
            os.rename(self._p(old), self._p(new))
            events.append(("rename", new))
            return paramiko.SFTP_OK

        def posix_rename(self, old, new):
            os.replace(self._p(old), self._p(new))
            events.append(("rename", new))
            return paramiko.SFTP_OK

        def mkdir(self, path, attr):
            os.mkdir(self._p(path))
            return paramiko.SFTP_OK

    return _SFTP


class StubSFTPServer:
    def __init__(self, root, user, allowed_key_b64, host_key=None):
        self.root, self.user, self.allowed = str(root), user, allowed_key_b64
        self.host_key = host_key or paramiko.RSAKey.generate(2048)
        self.events: list = []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self._stop = False
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            t = paramiko.Transport(conn)
            t.add_server_key(self.host_key)
            t.set_subsystem_handler("sftp", paramiko.SFTPServer, make_sftp_server_class(self.root, self.events))
            try:
                t.start_server(server=_Auth(self.user, self.allowed))
            except Exception:  # noqa: BLE001 – z. B. Fingerabdruck-Abfrage ohne Anmeldung
                pass

    def close(self):
        self._stop = True
        self.sock.close()
