#!/usr/bin/env python3
#
# Copyright (c) 2022-2025, The Isaac Lab Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause
#
# This file defines a helper class for managing Isaac Lab Docker containers.
# It has been modified to dynamically set the DOCKER_DEFAULT_PLATFORM environment variable.
# On macOS (Darwin) the variable is set to "linux/arm64" while on other platforms it is left unset
# (so Docker will use its native defaults).

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .state_file import StateFile


class ContainerInterface:
    """A helper class for managing Isaac Lab containers."""

    def __init__(
        self,
        context_dir: Path,
        profile: str = "base",
        yamls: list[str] | None = None,
        envs: list[str] | None = None,
        statefile: StateFile | None = None,
    ):
        """
        Initialize the container interface with the given parameters.

        Args:
            context_dir: The context directory for Docker operations.
            profile: The profile name for the container. Defaults to "base".
            yamls: A list of YAML files to extend docker-compose settings.
            envs: A list of environment variable files to extend .env.base.
            statefile: An instance of StateFile for runtime state management.
        """
        # set the context directory
        self.context_dir = context_dir

        # create a state-file if not provided
        # the state file is a manager of run-time state variables that are saved to a file
        if statefile is None:
            self.statefile = StateFile(path=self.context_dir / ".container.cfg")
        else:
            self.statefile = statefile

        # set the profile and container name
        self.profile = profile
        if self.profile == "isaaclab":
            # Silently correct from isaaclab to base, because isaaclab is a commonly passed arg
            # but not a real profile
            self.profile = "base"

        self.container_name = f"isaac-lab-{self.profile}"
        self.image_name = f"isaac-lab-{self.profile}:latest"

        # Copy current environment and set DOCKER_DEFAULT_PLATFORM dynamically.
        # On macOS (Darwin) we set it to linux/arm64; on other platforms we leave it unset.
        self.environ = os.environ.copy()
        if platform.system() == "Darwin":
            self.environ['DOCKER_DEFAULT_PLATFORM'] = 'linux/arm64'

        # resolve the image extension through the passed yamls and envs
        self._resolve_image_extension(yamls, envs)
        # load the environment variables from the .env files
        self._parse_dot_vars()

    def is_container_running(self) -> bool:
        """Check if the container is running."""
        status = subprocess.run(
            ["docker", "container", "inspect", "-f", "{{.State.Status}}", self.container_name],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        return status == "running"

    def does_image_exist(self) -> bool:
        """Check if the Docker image exists."""
        result = subprocess.run(["docker", "image", "inspect", self.image_name], capture_output=True, text=True)
        return result.returncode == 0

    def start(self):
        """Build and start the Docker container using Docker Compose."""
        print(
            f"[INFO] Building the docker image and starting the container '{self.container_name}' in the background..."
        )
        # Build the base image.
        subprocess.run(
            [
                "docker",
                "compose",
                "--file", "docker-compose.yaml",
                "--env-file", ".env.base",
                "build",
                "isaac-lab-base",
            ],
            check=False,
            cwd=self.context_dir,
            env=self.environ,
        )
        # Start the container using the merged YAMLs and env files.
        subprocess.run(
            ["docker", "compose"]
            + self.add_yamls
            + self.add_profiles
            + self.add_env_files
            + ["up", "--detach", "--build", "--remove-orphans"],
            check=False,
            cwd=self.context_dir,
            env=self.environ,
        )

    def enter(self):
        """Enter the running container by executing a bash shell."""
        if self.is_container_running():
            print(f"[INFO] Entering the existing '{self.container_name}' container in a bash session...")
            subprocess.run([
                "docker",
                "exec",
                "--interactive",
                "--tty",
                *(["-e", f"DISPLAY={os.environ['DISPLAY']}"] if "DISPLAY" in os.environ else []),
                f"{self.container_name}",
                "bash",
            ])
        else:
            raise RuntimeError(f"The container '{self.container_name}' is not running.")

    def stop(self):
        """Stop the running container using Docker Compose."""
        if self.is_container_running():
            print(f"[INFO] Stopping the launched docker container '{self.container_name}'...")
            subprocess.run(
                ["docker", "compose"] + self.add_yamls + self.add_profiles + self.add_env_files + ["down"],
                check=False,
                cwd=self.context_dir,
                env=self.environ,
            )
        else:
            raise RuntimeError(f"Can't stop container '{self.container_name}' as it is not running.")

    def copy(self, output_dir: Path | None = None):
        """Copy artifacts from the running container to the host machine."""
        if self.is_container_running():
            print(f"[INFO] Copying artifacts from the '{self.container_name}' container...")
            if output_dir is None:
                output_dir = self.context_dir

            # create a directory to store the artifacts
            output_dir = output_dir.joinpath("artifacts")
            if not output_dir.is_dir():
                output_dir.mkdir()

            # define dictionary of mapping from docker container path to host machine path
            docker_isaac_lab_path = Path(self.dot_vars["DOCKER_ISAACLAB_PATH"])
            artifacts = {
                docker_isaac_lab_path.joinpath("logs"): output_dir.joinpath("logs"),
                docker_isaac_lab_path.joinpath("docs/_build"): output_dir.joinpath("docs"),
                docker_isaac_lab_path.joinpath("data_storage"): output_dir.joinpath("data_storage"),
            }
            # print the artifacts to be copied
            for container_path, host_path in artifacts.items():
                print(f"  - {container_path} -> {host_path}")
            for path in artifacts.values():
                shutil.rmtree(path, ignore_errors=True)

            # copy the artifacts
            for container_path, host_path in artifacts.items():
                subprocess.run(
                    [
                        "docker",
                        "cp",
                        f"{self.container_name}:{container_path}/",
                        f"{host_path}",
                    ],
                    check=False,
                )
            print("\n[INFO] Finished copying the artifacts from the container.")
        else:
            raise RuntimeError(f"The container '{self.container_name}' is not running.")

    def config(self, output_yaml: Path | None = None):
        """Generate a merged Docker Compose configuration."""
        print("[INFO] Configuring the passed options into a YAML...")
        output = ["--output", output_yaml] if output_yaml is not None else []
        subprocess.run(
            ["docker", "compose"] + self.add_yamls + self.add_profiles + self.add_env_files + ["config"] + output,
            check=False,
            cwd=self.context_dir,
            env=self.environ,
        )

    def _resolve_image_extension(self, yamls: list[str] | None = None, envs: list[str] | None = None):
        """Resolve additional YAML and environment file extensions for docker-compose."""
        self.add_yamls = ["--file", "docker-compose.yaml"]
        self.add_profiles = ["--profile", f"{self.profile}"]
        self.add_env_files = ["--env-file", ".env.base"]

        # extend env file based on profile
        if self.profile != "base":
            self.add_env_files += ["--env-file", f".env.{self.profile}"]

        # extend the env file based on the passed envs
        if envs is not None:
            for env in envs:
                self.add_env_files += ["--env-file", env]

        # extend the docker-compose.yaml based on the passed yamls
        if yamls is not None:
            for yaml in yamls:
                self.add_yamls += ["--file", yaml]

    def _parse_dot_vars(self):
        """Parse environment variables from the .env files into a dictionary."""
        self.dot_vars: dict[str, Any] = {}

        # check if the number of arguments is even for the env files
        if len(self.add_env_files) % 2 != 0:
            raise RuntimeError(
                "The parameters for env files are configured incorrectly. There should be an even number of arguments."
            )

        # read the environment variables from the .env files
        for i in range(1, len(self.add_env_files), 2):
            with open(self.context_dir / self.add_env_files[i]) as f:
                self.dot_vars.update(dict(line.strip().split("=", 1) for line in f if "=" in line))
