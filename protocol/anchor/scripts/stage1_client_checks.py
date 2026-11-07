"""Compile test identities into isolated client copies; never edit product policy."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = "EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH"
FEE = "9h6UJdZqUPNnShaUHkSoxvEeZ7gBeNxzXGQcShhBnzEP"


def build(directory, program, fee):
    assert program == "5TU6hcKXiVt3Lttw7VLu4Jq18FeAgiURk5WxBVYAGGYt"
    target = directory / "client-checks"
    target.mkdir()
    (target / "node_modules").symlink_to(ROOT / "web/portal/node_modules", target_is_directory=True)
    manifest = {}
    sources = ["web/portal/src/lib/portalTransactionIntent.ts", "ios/BoulderRoller/Money/BalanceTransactionFirewall.swift",
               "ios/BoulderRoller/Money/SolanaProgramAddress.swift", "ios/BoulderRoller/Money/SolanaTransaction.swift"]
    for source in sources:
        original = (ROOT / source).read_text()
        text = original
        if source.endswith(("portalTransactionIntent.ts", "BalanceTransactionFirewall.swift")):
            for before, after in [(PROGRAM, program), (FEE, fee)]:
                assert text.count(before) == 1, source
                text = text.replace(before, after)
        (target / Path(source).name).write_text(text)
        manifest[source] = {"production_sha256": hashlib.sha256(original.encode()).hexdigest(),
                            "localnet_sha256": hashlib.sha256(text.encode()).hexdigest()}
    shutil.copyfile(ROOT / "web/portal/scripts/check-stage1-localnet.mts", target / "check.mts")
    shutil.copyfile(ROOT / "ios/scripts/stage1_localnet_check.swift", target / "main.swift")
    subprocess.run(["swiftc", "-O", "-o", str(target / "native-check"),
        *[str(target / name) for name in ("BalanceTransactionFirewall.swift", "SolanaProgramAddress.swift", "SolanaTransaction.swift", "main.swift")]], check=True)
    return {"STAGE1_PORTAL_POLICY": str(target / "portalTransactionIntent.ts"),
            "STAGE1_PORTAL_CHECK": str(target / "check.mts"), "STAGE1_NATIVE_CHECK": str(target / "native-check")}, manifest
