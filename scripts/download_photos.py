"""Download unlabelled Pi photos over SSH/SFTP and rotate PC copies."""
from __future__ import annotations

import argparse
import getpass
import json
import shutil
import stat
import sys
import tempfile
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path, PurePosixPath


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}


def checked_name(name: str) -> str:
    """Remote names must also be safe, unambiguous Windows path components."""
    if (
        not name or name in {".", ".."} or name.endswith((".", " "))
        or any(ord(char) < 32 or char in '<>:"/\\|?*' for char in name)
        or name.split(".")[0].upper() in WINDOWS_RESERVED
    ):
        raise ValueError(f"PC에 저장할 수 없는 파일/폴더 이름: {name!r}")
    return name


def remote_images(sftp, root: str, relative: PurePosixPath = PurePosixPath()):
    # lstat-like directory entries: never follow remote symbolic links.
    for entry in sorted(sftp.listdir_attr(str(PurePosixPath(root) / relative)), key=lambda e: e.filename):
        if stat.S_ISLNK(entry.st_mode):
            continue
        path = relative / checked_name(entry.filename)
        if stat.S_ISDIR(entry.st_mode):
            yield from remote_images(sftp, root, path)
        elif stat.S_ISREG(entry.st_mode) and path.suffix.lower() in IMAGE_SUFFIXES:
            yield path


def rotate_photo(source: Path, destination: Path, rotation: int) -> None:
    from PIL import Image, ImageOps

    if rotation not in (0, 180):
        raise ValueError("회전은 0도 또는 180도만 지원합니다.")
    # One decoded image at a time; context managers release native pixel buffers.
    with Image.open(source) as opened:
        with ImageOps.exif_transpose(opened) as oriented:
            with oriented.convert("RGB") as rgb:
                with (rgb.transpose(Image.Transpose.ROTATE_180) if rotation else rgb.copy()) as result:
                    if destination.suffix.lower() in {".jpg", ".jpeg"}:
                        result.save(destination, format="JPEG", quality=95, subsampling=0)
                    else:
                        result.save(destination, format="PNG")


def transfer_photos(sftp, remote_project: str, output: Path, rotation: int = 180,
                    class_name: str | None = None) -> int:
    """Create a new destination, keeping successful photos if interrupted."""
    project = PurePosixPath(remote_project)
    if not project.is_absolute() or ".." in project.parts:
        raise ValueError("라파 프로젝트 경로는 ..이 없는 절대 경로로 입력하세요.")
    relative_start = PurePosixPath(checked_name(class_name)) if class_name else PurePosixPath()
    raw = str(project / "datasets" / "raw")
    output.mkdir(parents=True, exist_ok=False)
    report = {"remote_project": remote_project, "rotation_degrees": rotation,
              "class_name": class_name, "saved": 0, "status": "incomplete"}
    print(f"PC 저장 위치: {output}", flush=True)
    try:
        # Temporary raw downloads are on the same volume as the final copies.
        with tempfile.TemporaryDirectory(prefix=".transfer-", dir=output) as staging:
            temp = Path(staging)
            sftp.get(str(project / "training" / "classes.txt"), str(temp / "classes.txt"))
            shutil.move(str(temp / "classes.txt"), str(output / "classes.txt"))
            for relative in remote_images(sftp, raw, relative_start):
                remote = str(PurePosixPath(raw) / relative)
                destination = output / "raw" / Path(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                # Case-only differences on the Pi must not overwrite PC photos.
                if destination.exists():
                    raise FileExistsError(f"중복된 PC 파일 경로: {destination}")
                before = sftp.stat(remote)
                downloaded = temp / "download"
                sftp.get(remote, str(downloaded))
                after = sftp.stat(remote)
                if (before.st_size, before.st_mtime) != (after.st_size, after.st_mtime):
                    raise OSError(f"전송 중 사진이 변경됐습니다. 촬영을 끝내고 다시 실행하세요: {relative}")
                if downloaded.stat().st_size != after.st_size:
                    raise OSError(f"사진을 완전히 받지 못했습니다: {relative}")
                converted = temp / ("rotated" + relative.suffix.lower())
                rotate_photo(downloaded, converted, rotation)
                # A half-downloaded or half-encoded file never appears in raw/.
                converted.replace(destination)
                downloaded.unlink()
                report["saved"] += 1
                print(f"[{report['saved']}] {relative}", flush=True)
            if not report["saved"]:
                raise ValueError("복사할 JPG/PNG 사진이 없습니다. 촬영 폴더를 확인하세요.")
            report["status"] = "complete"
    finally:
        (output / "transfer.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report["saved"]


def main() -> int:
    parser = argparse.ArgumentParser(description="PC에서 실행: SSH로 사진을 받아 180도 회전 저장")
    parser.add_argument("--host", required=True, help="라파 IP 주소")
    parser.add_argument("--user", default="pi30304", help="SSH 사용자명 (기본 pi30304)")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--remote-project", help="라파 프로젝트 절대 경로")
    parser.add_argument("--output", type=Path, help="새로 만들 PC 폴더 (기존 폴더는 사용 불가)")
    parser.add_argument("--class-name", help="한 종류만 복사 (예: raspberry_pi)")
    parser.add_argument("--rotation", type=int, choices=(0, 180), default=180)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("포트는 1~65535 사이여야 합니다.")
    try:
        import paramiko
        from PIL import Image  # noqa: F401
    except ImportError:
        print("PC에서 먼저 실행하세요: python -m pip install -r requirements-photo-transfer.txt", file=sys.stderr)
        return 1
    output = (args.output or Path.home() / "Downloads" / (
        "equipment-photos-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    )).expanduser().resolve()
    if output.exists():
        parser.error(f"기존 사진·라벨 보호를 위해 새 폴더를 지정하세요: {output}")
    project = args.remote_project or f"/home/{args.user}/raspberry-pi-equipment-manager"
    try:
        with closing(paramiko.SSHClient()) as client:
            # Use the host identity already trusted by Windows OpenSSH.
            known_hosts = Path.home() / ".ssh" / "known_hosts"
            if known_hosts.exists():
                client.load_host_keys(str(known_hosts))
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            password = getpass.getpass(f"{args.user}@{args.host} SSH 비밀번호 (화면에 표시 안 됨): ")
            try:
                client.connect(args.host, port=args.port, username=args.user, password=password,
                               look_for_keys=False, allow_agent=False, timeout=10,
                               banner_timeout=10, auth_timeout=15)
            finally:
                password = None
            with closing(client.open_sftp()) as sftp:
                sftp.get_channel().settimeout(30)
                count = transfer_photos(sftp, project, output, args.rotation, args.class_name)
        print(f"완료: {count}장 · {args.rotation}도 회전 · {output / 'raw'}")
        print("라파 원본은 보존했습니다. 이 PC 폴더의 사진으로 라벨링하세요.")
        return 0
    except KeyboardInterrupt:
        print(f"\n중단했습니다. 이미 완료된 사진은 남아 있습니다: {output}", file=sys.stderr)
        return 130
    except (OSError, ValueError, paramiko.SSHException) as exc:
        print(f"실패: {exc}\n저장 위치: {output}", file=sys.stderr)
        if "known_hosts" in str(exc):
            print(f"먼저 PC에서 ssh -p {args.port} {args.user}@{args.host} 로 접속해 장치를 확인하세요.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
