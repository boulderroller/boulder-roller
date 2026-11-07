"""Protect API credentials from same-user decoder children on Linux."""
import ctypes
import os
import sys


def protect_process_environment() -> None:
    if sys.platform != "linux":
        return
    libc = ctypes.CDLL(None, use_errno=True)
    prctl = libc.prctl
    prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    prctl.restype = ctypes.c_int
    # PR_SET_DUMPABLE=4: blocks same-UID procfs/ptrace access as well as core dumps.
    # Fail startup if the kernel cannot enforce this; never continue unprotected.
    if prctl(4, 0, 0, 0, 0) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
