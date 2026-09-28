"""macOS 原生 xattr 接口；CPython 的 os.xattr 系列仅在 Linux 提供。"""
import ctypes
import errno
import os


def _library():
    lib = ctypes.CDLL(None, use_errno=True)
    lib.fgetxattr.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p,
                             ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
    lib.fgetxattr.restype = ctypes.c_ssize_t
    lib.fremovexattr.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    lib.fremovexattr.restype = ctypes.c_int
    return lib


def has_quarantine(target):
    owned = not isinstance(target, int)
    fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW) if owned else target
    try:
        result = _library().fgetxattr(fd, b'com.apple.quarantine', None, 0, 0, 0)
        if result >= 0: return True
        number = ctypes.get_errno()
        if number == getattr(errno, 'ENOATTR', 93): return False
        raise OSError(number, os.strerror(number))
    finally:
        if owned: os.close(fd)


def remove_quarantine(fd):
    if _library().fremovexattr(fd, b'com.apple.quarantine', 0) != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))
