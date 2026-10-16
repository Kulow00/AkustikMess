"""SFTP-Upload: Schlüssel, Server-Erkennung, sichere Reihenfolge, nur Änderungen."""

import pytest

from sftp_stub import StubSFTPServer
from tools import deploy


@pytest.fixture
def env(tmp_path):
    key = tmp_path / "deploy_key"
    line = deploy.generate_deploy_key(key, comment="test")
    assert line.startswith("ssh-ed25519 ") and line.endswith(" test")
    remote = tmp_path / "server"
    (remote / "www").mkdir(parents=True)
    srv = StubSFTPServer(remote, "akmess-deploy", line.split()[1])
    cfg = {"host": "127.0.0.1", "port": srv.port, "user": "akmess-deploy", "remote_dir": "/www"}
    known = tmp_path / "known_hosts"
    publish = tmp_path / "web"
    (publish / "files").mkdir(parents=True)
    (publish / "files" / "AkustikMess-1.0.0-Windows-Setup.exe").write_bytes(b"x" * 300_000)
    (publish / "index.html").write_text("<html>")
    (publish / "CHANGELOG.md").write_text("# Log")
    (publish / "releases.json").write_text('{"signed": "{}", "signature": ""}')
    yield {"srv": srv, "cfg": cfg, "key": key, "known": known, "publish": publish, "remote": remote / "www",
           "state": tmp_path / "state.json"}
    srv.close()


def connect(e):
    return deploy.SFTP(e["cfg"], key_file=e["key"], known_hosts=e["known"])


def trust(e):
    fp = deploy.fingerprint(deploy.fetch_host_key("127.0.0.1", e["srv"].port))
    assert fp.startswith("SHA256:")
    deploy.trust_host("127.0.0.1", e["srv"].port, fp, e["known"])


def test_unknown_or_wrong_server_is_rejected(env):
    with pytest.raises(deploy.DeployError, match="sftp-setup"):
        connect(env)                                            # noch nicht bestätigt
    with pytest.raises(deploy.DeployError, match="stimmt nicht"):
        deploy.trust_host("127.0.0.1", env["srv"].port, "SHA256:falsch", env["known"])
    trust(env)
    connect(env).close()
    # Server bekommt einen anderen Schlüssel (z. B. Angreifer dazwischen) → Abbruch
    import paramiko
    env["srv"].host_key = paramiko.RSAKey.generate(2048)
    with pytest.raises(deploy.DeployError, match="ANDEREN Host-Schlüssel"):
        connect(env)


def test_wrong_client_key_is_rejected(env, tmp_path):
    trust(env)
    other = tmp_path / "other_key"
    deploy.generate_deploy_key(other)
    with pytest.raises(deploy.DeployError, match="authorized_keys"):
        deploy.SFTP(env["cfg"], key_file=other, known_hosts=env["known"])


def run_upload(env, connect_fn=None, log=None):
    return deploy.upload(env["cfg"], env["publish"], log=log or (lambda *_: None), state_file=env["state"],
                         connect=connect_fn or (lambda: connect(env)), retry_wait=0.01)


def test_upload_order_atomic_and_incremental(env):
    trust(env)
    with connect(env) as conn:
        conn.check_writable()
    done = run_upload(env)
    assert done[-2:] == ["index.html", "releases.json"]          # Verzeichnis ganz zuletzt
    renames = [p for kind, p in env["srv"].events if kind == "rename"]
    assert renames[-1] == "/www/releases.json"                   # erst .part, dann umbenannt
    assert (env["remote"] / "files" / "AkustikMess-1.0.0-Windows-Setup.exe").stat().st_size == 300_000
    assert not list(env["remote"].rglob("*.part"))
    assert run_upload(env) == []                                 # nichts geändert → nichts hochladen
    # neue Version: nur Installer und Verzeichnis
    (env["publish"] / "files" / "AkustikMess-1.0.1-Windows-Setup.exe").write_bytes(b"y" * 1000)
    (env["publish"] / "releases.json").write_text('{"signed": "{\\"v\\":2}", "signature": ""}')
    assert run_upload(env) == ["files/AkustikMess-1.0.1-Windows-Setup.exe", "releases.json"]
    assert (env["remote"] / "releases.json").read_text() == (env["publish"] / "releases.json").read_text()


def big_installer(env, size=3_000_000):
    data = bytes(range(256)) * (size // 256)
    p = env["publish"] / "files" / "AkustikMess-1.0.0-Windows-Setup.exe"
    p.write_bytes(data)
    return data


def test_connection_drop_retries_and_resumes(env):
    """Wie beim echten Upload: Verbindung reißt bei ~93 % ab → neu verbinden, ab dort fortsetzen."""
    trust(env)
    data = big_installer(env)
    drops = {"n": 0}

    class Flaky(deploy.SFTP):
        def put_atomic(self, local, remote_rel, progress=None):
            if remote_rel.endswith(".exe") and drops["n"] == 0:
                drops["n"] += 1
                self._mkdirs("/www/files")
                with self.sftp.open(f"/www/{remote_rel}.part", "wb") as fh:
                    fh.write(data[:2_800_000])           # Teil kam an, dann Abbruch
                raise EOFError()
            return super().put_atomic(local, remote_rel, progress)

    lines = []
    done = run_upload(env, lambda: Flaky(env["cfg"], key_file=env["key"], known_hosts=env["known"]),
                      log=lines.append)
    assert done[-1] == "releases.json" and drops["n"] == 1
    assert (env["remote"] / "files" / "AkustikMess-1.0.0-Windows-Setup.exe").read_bytes() == data
    text = "\n".join(lines)
    assert "neuer Versuch 2/4" in text and "setze bei 2.8 MB fort" in text and "100 %" in text


def test_corrupt_partial_is_not_resumed(env):
    trust(env)
    data = big_installer(env)
    part = env["remote"] / "files" / "AkustikMess-1.0.0-Windows-Setup.exe.part"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"\x00" * 1_000_000)                  # passt nicht zur lokalen Datei
    lines = []
    run_upload(env, log=lines.append)
    assert (env["remote"] / "files" / "AkustikMess-1.0.0-Windows-Setup.exe").read_bytes() == data
    assert not any("setze bei" in l for l in lines)        # komplett neu hochgeladen


def test_gives_up_after_retries(env):
    trust(env)
    big_installer(env)

    class Dead(deploy.SFTP):
        def put_atomic(self, local, remote_rel, progress=None):
            raise EOFError()

    with pytest.raises(deploy.DeployError, match="nach 4 Versuchen"):
        run_upload(env, lambda: Dead(env["cfg"], key_file=env["key"], known_hosts=env["known"]))
