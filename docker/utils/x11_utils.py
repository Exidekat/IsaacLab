#!/usr/bin/env python3

# Copyright (c) 2022-2025, The Isaac Lab Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause
#
# This module provides utility functions for managing X11 forwarding in the Docker container.
# It has been modified to support macOS by adapting the mktemp command to the BSD syntax.

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .state_file import StateFile


# This method of x11 enabling forwarding was inspired by osrf/rocker
# https://github.com/osrf/rocker
def configure_x11(statefile: StateFile) -> dict[str, str]:
    """Configure X11 forwarding by creating and managing a temporary .xauth file.

    If xauth is not installed, prints an error message and exits.

    Args:
        statefile: An instance of the state file manager.

    Returns:
        A dictionary with two keys:
            "__ISAACLAB_TMP_XAUTH": path to the temporary .xauth file.
            "__ISAACLAB_TMP_DIR": directory where the .xauth file is stored.
    """
    # check if xauth is installed
    if not shutil.which("xauth"):
        print("[INFO] xauth is not installed.")
        print("[INFO] Please install it with 'apt install xauth'")
        exit(1)

    # set the namespace to X11 for the statefile
    statefile.namespace = "X11"
    # load the value of the temporary xauth file
    tmp_xauth_value = statefile.get_variable("__ISAACLAB_TMP_XAUTH")

    if tmp_xauth_value is None or not Path(tmp_xauth_value).exists():
        # create a temporary directory to store the .xauth file
        tmp_dir = subprocess.run(["mktemp", "-d"], capture_output=True, text=True, check=True).stdout.strip()
        # create the .xauth file
        tmp_xauth_value = create_x11_tmpfile(tmpdir=Path(tmp_dir))
        # set the statefile variable
        statefile.set_variable("__ISAACLAB_TMP_XAUTH", str(tmp_xauth_value))
    else:
        tmp_dir = Path(tmp_xauth_value).parent

    return {"__ISAACLAB_TMP_XAUTH": str(tmp_xauth_value), "__ISAACLAB_TMP_DIR": str(tmp_dir)}


def x11_check(statefile: StateFile) -> tuple[list[str], dict[str, str]] | None:
    """Check and configure X11 forwarding based on the state file.

    Prompts the user to enable forwarding if not already configured. Returns the docker-compose
    x11 configuration and corresponding environment variables if enabled.

    Args:
        statefile: An instance of the state file manager.

    Returns:
        A tuple with a list (for docker-compose '--file x11.yaml') and a dictionary of environment variables,
        or None if forwarding is disabled.
    """
    # set the namespace to X11 for the statefile
    statefile.namespace = "X11"
    # check if X11 forwarding is enabled
    is_x11_forwarding_enabled = statefile.get_variable("X11_FORWARDING_ENABLED")

    if is_x11_forwarding_enabled is None:
        print("[INFO] X11 forwarding from the Isaac Lab container is disabled by default.")
        print("[INFO] It will fail if there is no display or if running via ssh without proper configuration.")
        x11_answer = input("Would you like to enable it? (y/N) ")

        # parse the user's input
        if x11_answer.lower() == "y":
            is_x11_forwarding_enabled = "1"
            print("[INFO] X11 forwarding is enabled from the container.")
        else:
            is_x11_forwarding_enabled = "0"
            print("[INFO] X11 forwarding is disabled from the container.")

        # remember the user's choice and set the statefile variable
        statefile.set_variable("X11_FORWARDING_ENABLED", is_x11_forwarding_enabled)
    else:
        # print the current configuration
        print(f"[INFO] X11 Forwarding is configured as '{is_x11_forwarding_enabled}' in '.container.cfg'.")

        # print help message to enable/disable X11 forwarding
        if is_x11_forwarding_enabled == "1":
            print("	To disable X11 forwarding, set 'X11_FORWARDING_ENABLED=0' in '.container.cfg'.")
        else:
            print("	To enable X11 forwarding, set 'X11_FORWARDING_ENABLED=1' in '.container.cfg'.")

    if is_x11_forwarding_enabled == "1":
        x11_envars = configure_x11(statefile)
        # If X11 forwarding is enabled, return the proper args to
        # compose the x11.yaml file. Else, return an empty string.
        return ["--file", "x11.yaml"], x11_envars

    return None


def x11_cleanup(statefile: StateFile):
    """Clean up the temporary .xauth file used for X11 forwarding."""
    statefile.namespace = "X11"

    # load the value of the temporary xauth file
    tmp_xauth_value = statefile.get_variable("__ISAACLAB_TMP_XAUTH")

    # if the file exists, delete it and remove the state variable
    if tmp_xauth_value is not None and Path(tmp_xauth_value).exists():
        print(f"[INFO] Removing temporary Isaac Lab '.xauth' file: {tmp_xauth_value}.")
        Path(tmp_xauth_value).unlink()
        statefile.delete_variable("__ISAACLAB_TMP_XAUTH")


def create_x11_tmpfile(tmpfile: Path | None = None, tmpdir: Path | None = None) -> Path:
    """Creates an .xauth file with an MIT-MAGIC-COOKIE derived from the current DISPLAY.

    Args:
        tmpfile: Optional. A Path to a file to use.
        tmpdir: Optional. A Path to the directory for a temporary file.

    Returns:
        The Path to the created .xauth file.
    """
    if tmpfile is None:
        if sys.platform == "darwin":
            # Use BSD mktemp syntax on macOS.
            result = subprocess.run(["mktemp", "-t", "xauth"], capture_output=True, text=True, check=True)
            tmp_xauth = Path(result.stdout.strip())
        else:
            args = ["mktemp", "--suffix=.xauth"]
            if tmpdir is not None:
                args.append(f"--tmpdir={tmpdir}")
            result = subprocess.run(args, capture_output=True, text=True, check=True)
            tmp_xauth = Path(result.stdout.strip())
    else:
        tmpfile.touch()
        tmp_xauth = tmpfile

    # Derive current MIT-MAGIC-COOKIE and make it universally addressable
    xauth_cookie = subprocess.run(
        ["xauth", "nlist", os.environ["DISPLAY"]], capture_output=True, text=True, check=True
    ).stdout.replace("ffff", "")

    subprocess.run(["xauth", "-f", str(tmp_xauth), "nmerge", "-"], input=xauth_cookie, text=True, check=True)

    return tmp_xauth


def x11_refresh(statefile: StateFile):
    """Refresh the temporary .xauth file used for X11 forwarding.

    This creates a new .xauth file if needed, ensuring the cookie is up-to-date.
    """
    # set the namespace to X11 for the statefile
    statefile.namespace = "X11"

    # check if X11 forwarding is enabled
    is_x11_forwarding_enabled = statefile.get_variable("X11_FORWARDING_ENABLED")
    # load the value of the temporary xauth file
    tmp_xauth_value = statefile.get_variable("__ISAACLAB_TMP_XAUTH")

    # print the current configuration
    if is_x11_forwarding_enabled is not None:
        status = "enabled" if is_x11_forwarding_enabled == "1" else "disabled"
        print(f"[INFO] X11 Forwarding is {status} from the settings in '.container.cfg'")

    # if the file exists, delete it and create a new one
    if tmp_xauth_value is not None and Path(tmp_xauth_value).exists():
        # remove the file and create a new one
        Path(tmp_xauth_value).unlink()
        create_x11_tmpfile(tmpfile=Path(tmp_xauth_value))
        # update the statefile with the new path
        statefile.set_variable("__ISAACLAB_TMP_XAUTH", str(tmp_xauth_value))
    elif tmp_xauth_value is None:
        if is_x11_forwarding_enabled == "1":
            print(
                "[ERROR] X11 forwarding is enabled but the temporary .xauth file does not exist."
                " Please rebuild the container by running: './docker/container.py start'"
            )
            sys.exit(1)
        else:
            print("[INFO] X11 forwarding is disabled. No action taken.")
