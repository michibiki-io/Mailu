"""Start real admin with disposable SQLite/Redis and no public DNS preflight."""
import os
import shutil
import subprocess

from socrate import system

shutil.chown("/data", user="mailu", group="mailu")
shutil.chown("/dkim", user="mailu", group="mailu")
system.drop_privs_to("mailu")
system.set_env(["SECRET"])
subprocess.run(["flask", "db", "upgrade"], check=True)
subprocess.run(["flask", "mailu", "admin", "alice", "example.org", "fixture-only-password"], check=True)
os.execvp("gunicorn", ["gunicorn", "-b", "0.0.0.0:8080", "--access-logfile", "-", "mailu:create_app()"])
