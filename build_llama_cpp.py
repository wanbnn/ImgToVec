#!/usr/bin/env python3
"""Baixa e compila o llama.cpp com o melhor backend disponível no host."""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE_DIR = ROOT / "llama.cpp"


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None,
        dry_run: bool = False) -> None:
    print("+", " ".join(command))
    if not dry_run:
        subprocess.run(command, cwd=cwd, env=env, check=True)


def command_exists(name: str) -> bool:
    return executable_path(name) is not None


def executable_path(name: str) -> str | None:
    """Encontra ferramentas inclusive na localização padrão do ROCm."""
    found = shutil.which(name)
    if found:
        return found
    candidate = Path("/opt/rocm/bin") / name
    return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None


def has_amd_gpu() -> bool:
    """Detecta uma GPU AMD pelo driver do kernel, sem depender do ROCm."""
    for uevent in Path("/sys/class/drm").glob("card*/device/uevent"):
        try:
            content = uevent.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "DRIVER=amdgpu" in content or "PCI_ID=1002:" in content:
            return True
    return False


def linux_family() -> str:
    values: dict[str, str] = {}
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value.strip().strip('"')
    except OSError:
        return "unknown"
    names = f"{values.get('ID', '')} {values.get('ID_LIKE', '')}".lower()
    if any(item in names for item in ("ubuntu", "debian", "pop")):
        return "apt"
    if any(item in names for item in ("arch", "manjaro", "endeavouros")):
        return "pacman"
    if any(item in names for item in ("fedora", "rhel", "centos", "rocky")):
        return "dnf"
    if any(item in names for item in ("opensuse", "suse")):
        return "zypper"
    return "unknown"


def install_build_dependencies(dry_run: bool) -> None:
    missing = [tool for tool in ("git", "cmake") if not command_exists(tool)]
    if not missing and (command_exists("c++") or command_exists("g++") or command_exists("clang++")):
        return

    if platform.system() == "Darwin":
        if not command_exists("clang++"):
            run(["xcode-select", "--install"], dry_run=dry_run)
        if (not command_exists("cmake") or not command_exists("git")) and command_exists("brew"):
            run(["brew", "install", "cmake", "git", "ninja"], dry_run=dry_run)
            return
        if not command_exists("cmake"):
            raise RuntimeError("Instale o CMake (por exemplo: brew install cmake).")
        return

    manager = linux_family()
    prefix = [] if os.geteuid() == 0 else ["sudo"]
    commands = {
        "apt": [
            prefix + ["apt-get", "update"],
            prefix + ["apt-get", "install", "-y", "build-essential", "cmake", "git", "ninja-build", "libcurl4-openssl-dev"],
        ],
        "pacman": [prefix + ["pacman", "-S", "--needed", "--noconfirm", "base-devel", "cmake", "git", "ninja", "curl"]],
        "dnf": [prefix + ["dnf", "install", "-y", "gcc-c++", "cmake", "git", "ninja-build", "libcurl-devel"]],
        "zypper": [prefix + ["zypper", "--non-interactive", "install", "-t", "pattern", "devel_basis"],
                    prefix + ["zypper", "--non-interactive", "install", "cmake", "git", "ninja", "libcurl-devel"]],
    }
    if manager not in commands:
        raise RuntimeError("Distribuição não reconhecida. Instale git, cmake e um compilador C++17.")
    for command in commands[manager]:
        run(command, dry_run=dry_run)


def install_rocm_dependencies(dry_run: bool) -> None:
    """Instala o SDK HIP quando a distribuição já o oferece oficialmente."""
    if command_exists("hipconfig") and command_exists("rocminfo"):
        return
    if platform.system() != "Linux":
        raise RuntimeError("ROCm/HIP é suportado por este instalador somente no Linux.")

    manager = linux_family()
    prefix = [] if os.geteuid() == 0 else ["sudo"]
    if manager == "pacman":
        run(prefix + ["pacman", "-S", "--needed", "--noconfirm", "rocm-hip-sdk", "rocminfo"], dry_run=dry_run)
        return

    # Em Ubuntu/Pop!_OS, Fedora e openSUSE os nomes só funcionam depois que o
    # repositório ROCm adequado à versão do sistema estiver configurado.
    candidates = {
        "apt": ["apt-get", "install", "-y", "rocm-hip-sdk", "rocminfo"],
        "dnf": ["dnf", "install", "-y", "rocm-hip-sdk", "rocminfo"],
        "zypper": ["zypper", "--non-interactive", "install", "rocm-hip-sdk", "rocminfo"],
    }
    if manager not in candidates:
        raise RuntimeError("Distribuição não reconhecida para instalar ROCm automaticamente.")
    try:
        run(prefix + candidates[manager], dry_run=dry_run)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            "O repositório ROCm não está configurado nesta distribuição. "
            "Configure-o conforme https://rocm.docs.amd.com/projects/install-on-linux/ e execute novamente."
        ) from error


def detect_backend(requested: str, *, allow_missing_toolkit: bool = False) -> str:
    system = platform.system()
    if requested != "auto":
        if requested == "metal" and system != "Darwin":
            raise RuntimeError("Metal só está disponível no macOS.")
        if requested == "cuda" and not command_exists("nvcc") and not allow_missing_toolkit:
            raise RuntimeError("CUDA solicitado, mas 'nvcc' não foi encontrado. Instale o CUDA Toolkit.")
        if requested == "rocm" and not command_exists("hipconfig") and not allow_missing_toolkit:
            raise RuntimeError("ROCm solicitado, mas 'hipconfig' não foi encontrado. Instale ROCm/HIP 6.1+.")
        return requested
    if system == "Darwin":
        return "metal"
    if command_exists("nvidia-smi") and command_exists("nvcc"):
        return "cuda"
    if command_exists("hipconfig") and has_amd_gpu():
        return "rocm"
    if command_exists("nvidia-smi"):
        print("Aviso: GPU NVIDIA encontrada, mas o CUDA Toolkit/nvcc não; usando CPU.")
    return "cpu"


def primary_amd_bdfid() -> int | None:
    """Retorna o BDFID da GPU AMD com mais VRAM (normalmente a discreta)."""
    candidates: list[tuple[int, int]] = []
    for card in Path("/sys/class/drm").glob("card[0-9]*"):
        uevent = card / "device/uevent"
        try:
            values = dict(
                line.split("=", 1)
                for line in uevent.read_text(encoding="utf-8", errors="replace").splitlines()
                if "=" in line
            )
            if values.get("DRIVER") != "amdgpu" and not values.get("PCI_ID", "").startswith("1002:"):
                continue
            # Formato sysfs: domínio:bus:dispositivo.função. O HSA usa
            # (domínio << 16) | (bus << 8) | (dispositivo << 3) | função.
            domain, bus, device_function = values["PCI_SLOT_NAME"].split(":")
            device, function = device_function.split(".")
            bdfid = (int(domain, 16) << 16) | (int(bus, 16) << 8) | (int(device, 16) << 3) | int(function, 16)
            vram_file = card / "device/mem_info_vram_total"
            vram = int(vram_file.read_text().strip()) if vram_file.is_file() else 0
            candidates.append((vram, bdfid))
        except (OSError, KeyError, ValueError):
            continue
    return max(candidates)[1] if candidates else None


def rocm_targets() -> list[str]:
    """Obtém o alvo ROCm da GPU AMD principal, ignorando nomes de família."""
    rocminfo = executable_path("rocminfo")
    if not rocminfo:
        return []
    result = subprocess.run([rocminfo], text=True, capture_output=True, check=False)
    agents: list[tuple[int | None, str]] = []
    for block in re.split(r"(?=^\s*Agent\s+\d+\s*$)", result.stdout, flags=re.MULTILINE):
        # Exige pelo menos três caracteres após "gfx". Isso rejeita aliases
        # de família como gfx9/gfx12, que o clang não aceita como arquitetura.
        name = re.search(r"^\s*Name:\s*(gfx[0-9a-f]{3,})\s*$", block, flags=re.IGNORECASE | re.MULTILINE)
        if not name or name.group(1).lower() == "gfx000":
            continue
        bdf = re.search(r"^\s*BDFID:\s*(\d+)\s*$", block, flags=re.MULTILINE)
        agents.append((int(bdf.group(1)) if bdf else None, name.group(1).lower()))

    primary_bdfid = primary_amd_bdfid()
    primary = [target for bdfid, target in agents if bdfid == primary_bdfid]
    if primary:
        return list(dict.fromkeys(primary))
    # Se uma plataforma não expuser BDFID/VRAM, mantém todos os alvos completos
    # encontrados. Nunca volta a aceitar os aliases inválidos gfx9/gfx12.
    return list(dict.fromkeys(target for _, target in agents))


def ensure_source(ref: str | None, dry_run: bool) -> None:
    if not SOURCE_DIR.exists():
        run(["git", "clone", "--depth", "1", "https://github.com/ggml-org/llama.cpp.git", str(SOURCE_DIR)], dry_run=dry_run)
    elif not (SOURCE_DIR / ".git").is_dir():
        raise RuntimeError(f"{SOURCE_DIR} existe, mas não é um clone Git do llama.cpp.")
    else:
        # --ff-only preserva qualquer trabalho local em vez de sobrescrevê-lo.
        run(["git", "pull", "--ff-only"], cwd=SOURCE_DIR, dry_run=dry_run)
    if ref:
        run(["git", "fetch", "--depth", "1", "origin", ref], cwd=SOURCE_DIR, dry_run=dry_run)
        run(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=SOURCE_DIR, dry_run=dry_run)


def build(backend: str, jobs: int, clean: bool, dry_run: bool) -> Path:
    build_dir = SOURCE_DIR / f"build-{backend}"
    if clean and build_dir.exists():
        print(f"Removendo build anterior: {build_dir}")
        if not dry_run:
            shutil.rmtree(build_dir)
    # O backend HTTP é dispensável para rodar modelos locais e exigiria headers
    # libcurl que nem sempre acompanham a instalação mínima da distribuição.
    flags = ["-DCMAKE_BUILD_TYPE=Release", "-DLLAMA_CURL=OFF"]
    env = os.environ.copy()
    if backend == "cuda":
        flags.append("-DGGML_CUDA=ON")
    elif backend == "rocm":
        flags.append("-DGGML_HIP=ON")
        targets = rocm_targets()
        if targets:
            flags.append(f"-DGPU_TARGETS={';'.join(targets)}")
            print(f"Arquitetura da GPU AMD principal: {', '.join(targets)}")
        else:
            print("Aviso: rocminfo não listou alvos; o CMake detectará as GPUs presentes.")
        hipconfig = executable_path("hipconfig")
        if hipconfig:
            hip_root = subprocess.run([hipconfig, "-R"], text=True, capture_output=True, check=True).stdout.strip()
            hip_clang = subprocess.run([hipconfig, "-l"], text=True, capture_output=True, check=True).stdout.strip()
            env["HIP_PATH"] = hip_root
            env["HIPCXX"] = str(Path(hip_clang) / "clang")
            env["PATH"] = f"/opt/rocm/bin:{env.get('PATH', '')}"
            env["CMAKE_PREFIX_PATH"] = f"/opt/rocm;{env.get('CMAKE_PREFIX_PATH', '')}".rstrip(";")

        # Uma configuração HIP que falhou deixa o teste do compilador no cache.
        # --fresh recria somente os metadados CMake e preserva fontes e binários.
        if (build_dir / "CMakeCache.txt").exists():
            flags.insert(0, "--fresh")
    elif backend == "metal":
        flags.append("-DGGML_METAL=ON")
    else:
        flags.extend(["-DGGML_CUDA=OFF", "-DGGML_HIP=OFF", "-DGGML_METAL=OFF"])

    run(["cmake", "-S", str(SOURCE_DIR), "-B", str(build_dir), *flags], env=env, dry_run=dry_run)
    run(["cmake", "--build", str(build_dir), "--config", "Release", "-j", str(jobs)], env=env, dry_run=dry_run)
    return build_dir / "bin"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("auto", "cpu", "cuda", "rocm", "metal"), default="auto")
    parser.add_argument("--jobs", type=int, default=max(1, os.cpu_count() or 1), help="processos paralelos de compilação")
    parser.add_argument("--ref", help="tag, branch ou commit do llama.cpp (padrão: branch atual oficial)")
    parser.add_argument("--clean", action="store_true", help="remove somente a pasta build-<backend> antes de compilar")
    parser.add_argument("--no-install-deps", action="store_true", help="não instala dependências básicas")
    parser.add_argument("--dry-run", action="store_true", help="mostra comandos sem executá-los")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.jobs < 1:
        raise ValueError("--jobs deve ser maior que zero")
    if not args.no_install_deps:
        install_build_dependencies(args.dry_run)
        if args.backend == "rocm" or (args.backend == "auto" and has_amd_gpu() and not command_exists("nvcc")):
            install_rocm_dependencies(args.dry_run)
    backend = detect_backend(args.backend, allow_missing_toolkit=args.dry_run)
    print(f"Sistema: {platform.system()} {platform.machine()} | backend: {backend}")
    ensure_source(args.ref, args.dry_run)
    output = build(backend, args.jobs, args.clean, args.dry_run)
    print(f"\nBuild pronta em: {output}")
    print(f"Executável principal: {output / 'llama-cli'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError, OSError, ValueError) as error:
        print(f"Erro: {error}", file=sys.stderr)
        raise SystemExit(1)
