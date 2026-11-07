import json
import os
from pathlib import Path
import subprocess

SCRIPT=Path(__file__).resolve().parents[2]/'scripts/deploy-backend-release.sh'

def test_public_release_requires_invites():
    text=SCRIPT.read_text()
    preflight=text.split("<<'PY'",1)[1].split('\nPY',1)[0]
    for public,invites,ok in [(True,False,False),(True,True,True),(False,False,True),(True,None,False)]:
        payload={'version':'test-sha','environment_public':public,'invite_required':invites}
        result=subprocess.run(['python3','-c',preflight],env={**os.environ,'EXPECTED_COMMIT':'test-sha','STATUS_PAYLOAD':json.dumps(payload)},capture_output=True,text=True)
        assert (result.returncode==0) is ok, result.stdout+result.stderr
