"""Build a scratch adapter against the pinned compiler, with no source edits."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

PIN = "f2594bec844472464cbf479f48940bc868f9370a"


def export(compiler, pbf, candidates, scratch):
    head = subprocess.check_output(["git", "-C", str(compiler), "rev-parse", "HEAD"], text=True).strip()
    if head != PIN:
        raise ValueError("compiler checkout does not match reviewed pin")
    subprocess.run(["git", "-C", str(compiler), "diff", "--exit-code", "HEAD", "--", "workout-parse/src", "workout-parse/Cargo.toml"], check=True)
    scratch.mkdir(parents=True, exist_ok=True)
    crate = scratch / "adapter"
    (crate / "src").mkdir(parents=True, exist_ok=True)
    manifest = '[package]\nname="stop-map-export"\nversion="0.1.0"\nedition="2021"\n[dependencies]\n'
    manifest += 'workout-parse={path=' + json.dumps(str(compiler / "workout-parse")) + ',default-features=false,features=["osm"]}\nserde_json="1"\n'
    manifest += '[profile.release]\nopt-level=2\nlto=false\n'
    (crate / "Cargo.toml").write_text(manifest)
    shutil.copyfile(Path(__file__).with_suffix(".rs"), crate / "src/main.rs")
    shutil.copyfile(compiler / "workout-parse/Cargo.lock", crate / "Cargo.lock")
    env = dict(os.environ, CARGO_TARGET_DIR=str(scratch / "target"))
    subprocess.run(["cargo", "build", "--offline", "--release", "--manifest-path", str(crate / "Cargo.toml"), "-j", "2"], env=env, check=True)
    subprocess.run([str(scratch / "target/release/stop-map-export"), str(pbf), str(candidates), str(scratch)], check=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["compiler", "pbf", "candidates", "scratch"]:
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    export(a.compiler, a.pbf, a.candidates, a.scratch)
