"""
windows_shell.py
================
What makes the Windows app behave like other Windows apps, with nothing but ctypes:

- set_app_id: the app's own AppUserModelID, the identity Windows groups its taskbar
  button, pinned taskbar and Start icons and jump list by. The installer gives its
  shortcuts the same ID (installer.iss), so a pinned icon and the open window are one.
- set_jump_list: tasks in the menu you get by right-clicking the app on the taskbar
  or Start (e.g. "Dock to the right"), each starting the app with arguments.
- AppBar: docks the window to the left or right edge of its screen the way the taskbar
  docks, so the screen's work area shrinks and maximized windows fit beside it.

Windows only; launcher.py only calls these on Windows (the module imports anywhere, for its tests).
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

LEFT, RIGHT = "left", "right"

# Windows' fixed-size types, spelled out: ctypes.wintypes makes DWORD a C long, which is
# 8 bytes off Windows, so structures built from these have Windows' layout everywhere.
DWORD, WORD, UINT, LONG = ctypes.c_uint32, ctypes.c_uint16, ctypes.c_uint32, ctypes.c_int32


class RECT(ctypes.Structure):
    _fields_ = [("left", LONG), ("top", LONG), ("right", LONG), ("bottom", LONG)]


# ------------------------------------------------------------- app identity --
def set_app_id(app_id: str) -> None:
    """Call before the app opens any window."""
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(app_id))


def app_id() -> str | None:
    """This process's AppUserModelID, if it set one."""
    out = ctypes.c_wchar_p()
    if ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID(ctypes.byref(out)) != 0:
        return None
    value = out.value
    ctypes.windll.ole32.CoTaskMemFree(out)
    return value


# --------------------------------------------------------------- jump list --
class GUID(ctypes.Structure):
    _fields_ = [("Data1", DWORD), ("Data2", WORD), ("Data3", WORD), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text: str) -> "GUID":
        guid = cls()
        ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(guid))
        return guid


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", DWORD)]


class PROPVARIANT(ctypes.Structure):
    # vt, three reserved WORDs, then a union at least two pointers wide (24 bytes on 64-bit)
    _fields_ = [("vt", WORD), ("reserved1", WORD), ("reserved2", WORD), ("reserved3", WORD),
                ("pwszVal", ctypes.c_void_p), ("padding", ctypes.c_void_p)]


CLSID_DestinationList = "{77F10CF0-3DB5-4966-B520-B7C54FD35ED6}"
CLSID_EnumerableObjectCollection = "{2D3468C1-36A7-43B6-AC24-D3F02FD9607A}"
CLSID_ShellLink = "{00021401-0000-0000-C000-000000000046}"
IID_ICustomDestinationList = "{6332DEBF-87B5-4670-90C0-5E57B408A49E}"
IID_IObjectArray = "{92CA9DCD-5622-4BBA-A805-5E9F541BD8C9}"
IID_IObjectCollection = "{5632B1A4-E38A-400A-928A-D4CD63230295}"
IID_IShellLinkW = "{000214F9-0000-0000-C000-000000000046}"
IID_IPropertyStore = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
PKEY_Title = ("{F29F85E0-4FF9-1068-AB91-08002B27B3D9}", 2)
VT_LPWSTR = 31
CLSCTX_INPROC_SERVER = 1
COINIT_APARTMENTTHREADED = 2

# vtable slots (IUnknown's QueryInterface, AddRef, Release are 0-2)
QUERY_INTERFACE, RELEASE = 0, 2
LINK_SET_DESCRIPTION, LINK_SET_ARGUMENTS, LINK_SET_ICON_LOCATION, LINK_SET_PATH = 7, 11, 17, 20
STORE_SET_VALUE, STORE_COMMIT = 6, 7
COLLECTION_ADD_OBJECT = 5
LIST_SET_APP_ID, LIST_BEGIN_LIST, LIST_ADD_USER_TASKS, LIST_COMMIT_LIST = 3, 4, 7, 8


def _method(obj: ctypes.c_void_p, slot: int, *argtypes, restype=None):
    """A COM method of `obj` by its vtable slot, returning an HRESULT (which raises OSError on
    failure) unless `restype` says otherwise."""
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype or ctypes.HRESULT, ctypes.c_void_p, *argtypes)(vtable[slot])


def _call(obj: ctypes.c_void_p, slot: int, *args: tuple) -> None:
    """Call a COM method; each arg is (ctypes type, value). An address passed as a value must be
    of an object the caller keeps in a variable until the call returns."""
    _method(obj, slot, *(t for t, _ in args))(obj, *(v for _, v in args))


def _create(clsid: str, iid: str) -> ctypes.c_void_p:
    obj = ctypes.c_void_p()
    ctypes.oledll.ole32.CoCreateInstance(ctypes.byref(GUID.parse(clsid)), None, CLSCTX_INPROC_SERVER,
                                         ctypes.byref(GUID.parse(iid)), ctypes.byref(obj))
    return obj


def _query(obj: ctypes.c_void_p, iid: str) -> ctypes.c_void_p:
    out, guid = ctypes.c_void_p(), GUID.parse(iid)  # held in variables: COM reads them during the call
    _call(obj, QUERY_INTERFACE, (ctypes.c_void_p, ctypes.addressof(guid)), (ctypes.c_void_p, ctypes.addressof(out)))
    return out


def _release(*objs: ctypes.c_void_p) -> None:
    for obj in objs:
        if obj:
            _method(obj, RELEASE, restype=ctypes.c_ulong)(obj)


def _build_jump_list(app_id: str, exe: str, tasks: list[tuple[str, str, str]]) -> None:
    held: list[ctypes.c_void_p] = []  # every interface we hold, released at the end
    keep: list = []  # buffers COM reads from during the calls
    try:
        dest = _create(CLSID_DestinationList, IID_ICustomDestinationList)
        held.append(dest)
        collection = _create(CLSID_EnumerableObjectCollection, IID_IObjectCollection)
        held.append(collection)
        key = PROPERTYKEY(GUID.parse(PKEY_Title[0]), PKEY_Title[1])
        for title, arguments, description in tasks:
            link = _create(CLSID_ShellLink, IID_IShellLinkW)
            held.append(link)
            _call(link, LINK_SET_PATH, (ctypes.c_wchar_p, exe))
            _call(link, LINK_SET_ARGUMENTS, (ctypes.c_wchar_p, arguments))
            _call(link, LINK_SET_ICON_LOCATION, (ctypes.c_wchar_p, exe), (ctypes.c_int, 0))
            _call(link, LINK_SET_DESCRIPTION, (ctypes.c_wchar_p, description))
            store = _query(link, IID_IPropertyStore)  # a task's name is its link's Title property
            held.append(store)
            text = ctypes.create_unicode_buffer(title)
            value = PROPVARIANT(vt=VT_LPWSTR, pwszVal=ctypes.cast(text, ctypes.c_void_p))
            keep += [text, value]
            _call(store, STORE_SET_VALUE, (ctypes.c_void_p, ctypes.addressof(key)),
                  (ctypes.c_void_p, ctypes.addressof(value)))
            _call(store, STORE_COMMIT)
            _call(collection, COLLECTION_ADD_OBJECT, (ctypes.c_void_p, link))
        _call(dest, LIST_SET_APP_ID, (ctypes.c_wchar_p, app_id))
        slots, removed, array_iid = UINT(), ctypes.c_void_p(), GUID.parse(IID_IObjectArray)
        _call(dest, LIST_BEGIN_LIST, (ctypes.c_void_p, ctypes.addressof(slots)),
              (ctypes.c_void_p, ctypes.addressof(array_iid)), (ctypes.c_void_p, ctypes.addressof(removed)))
        held.append(removed)
        array = _query(collection, IID_IObjectArray)
        held.append(array)
        _call(dest, LIST_ADD_USER_TASKS, (ctypes.c_void_p, array))
        _call(dest, LIST_COMMIT_LIST)
    finally:
        _release(*reversed(held))


def set_jump_list(app_id: str, exe: str, tasks: list[tuple[str, str, str]]) -> None:
    """Replace the app's jump list tasks: [(title, arguments for exe, description)]. Runs on
    its own thread, in a COM apartment of its own, so it can't upset the window's; raises
    OSError if Windows refused it."""
    failure: list[BaseException] = []

    def build() -> None:
        ctypes.oledll.ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        try:
            _build_jump_list(app_id, exe, tasks)
        except BaseException as e:
            failure.append(e)
        finally:
            ctypes.windll.ole32.CoUninitialize()

    worker = threading.Thread(target=build, name="jump-list", daemon=True)
    worker.start()
    worker.join(15)
    if worker.is_alive():
        raise OSError("Windows didn't answer while the jump list was being set")
    if failure:
        raise failure[0]


# ------------------------------------------------------------------ docking --
class APPBARDATA(ctypes.Structure):
    _fields_ = [("cbSize", DWORD), ("hWnd", ctypes.c_void_p), ("uCallbackMessage", UINT), ("uEdge", UINT),
                ("rc", RECT), ("lParam", ctypes.c_ssize_t)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", DWORD)]


ABM_NEW, ABM_REMOVE, ABM_QUERYPOS, ABM_SETPOS = 0, 1, 2, 3
ABE_LEFT, ABE_RIGHT = 0, 2
GWL_STYLE = -16
WS_CAPTION, WS_THICKFRAME = 0x00C00000, 0x00040000
SW_MAXIMIZE, SW_RESTORE = 3, 9
SWP_SHOWWINDOW, SWP_FRAMECHANGED = 0x0040, 0x0020
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
MONITOR_DEFAULTTONEAREST = 2
WM_APP = 0x8000
SPI_GETWORKAREA = 0x0030


def _user32():
    user32 = ctypes.windll.user32
    long_ptr = ctypes.c_ssize_t
    get_style = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)  # 32-bit Windows has no ...Ptr
    set_style = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
    get_style.argtypes, get_style.restype = [wintypes.HWND, ctypes.c_int], long_ptr
    set_style.argtypes, set_style.restype = [wintypes.HWND, ctypes.c_int, long_ptr], long_ptr
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, UINT]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.MonitorFromWindow.argtypes, user32.MonitorFromWindow.restype = [wintypes.HWND, DWORD], wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.IsZoomed.argtypes = [wintypes.HWND]
    return user32, get_style, set_style


def _shell_message(message: int, data: APPBARDATA) -> int:
    shell32 = ctypes.windll.shell32
    shell32.SHAppBarMessage.argtypes = [DWORD, ctypes.POINTER(APPBARDATA)]
    shell32.SHAppBarMessage.restype = ctypes.c_size_t
    return shell32.SHAppBarMessage(message, ctypes.byref(data))


def window_scale(hwnd: int) -> float:
    """The window's display scaling: 1.0 at 100%, 1.5 at 150%..."""
    try:
        dpi = ctypes.windll.user32.GetDpiForWindow(wintypes.HWND(hwnd))  # Windows 10 1607+
    except AttributeError:
        dpi = 96
    return (dpi or 96) / 96


def work_area() -> tuple[int, int, int, int]:
    """The primary screen's work area (left, top, right, bottom): what docked bars leave free."""
    rect = RECT()
    ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
    return rect.left, rect.top, rect.right, rect.bottom


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = RECT()
    ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


class AppBar:
    """Docks one window to the left or right edge of the screen it's on, the way the taskbar is
    docked: borderless, on top, and taking its strip of the screen out of the work area. undock()
    puts the window back as it was."""

    CALLBACK = WM_APP + 0x51  # Windows posts position changes here; the window ignores them

    def __init__(self, hwnd: int) -> None:
        self.hwnd = hwnd
        self.edge: str | None = None
        self._saved: tuple[int, tuple[int, int, int, int], bool] | None = None  # style, rect, maximized

    def _data(self) -> APPBARDATA:
        return APPBARDATA(cbSize=ctypes.sizeof(APPBARDATA), hWnd=self.hwnd, uCallbackMessage=self.CALLBACK)

    def dock(self, edge: str, width: int) -> tuple[int, int, int, int]:
        """Dock to `edge` (LEFT or RIGHT), `width` logical pixels wide; returns the window's new
        rectangle. Docking again (to either edge) just moves it."""
        user32, get_style, set_style = _user32()
        hwnd = wintypes.HWND(self.hwnd)
        if self.edge is None:
            maximized = bool(user32.IsZoomed(hwnd))
            user32.ShowWindow(hwnd, SW_RESTORE)
            self._saved = (get_style(hwnd, GWL_STYLE), window_rect(self.hwnd), maximized)
            if not _shell_message(ABM_NEW, self._data()):
                raise OSError("Windows wouldn't dock the app")
        monitor = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST), ctypes.byref(monitor))
        pixels = round(width * window_scale(self.hwnd))
        data = self._data()
        data.uEdge = ABE_RIGHT if edge == RIGHT else ABE_LEFT
        data.rc = monitor.rcMonitor

        def fit() -> None:  # the strip at the edge, as wide as asked
            if edge == RIGHT:
                data.rc.left = data.rc.right - pixels
            else:
                data.rc.right = data.rc.left + pixels

        fit()
        _shell_message(ABM_QUERYPOS, data)  # Windows moves it clear of the taskbar and other bars
        fit()
        _shell_message(ABM_SETPOS, data)
        set_style(hwnd, GWL_STYLE, self._saved[0] & ~(WS_CAPTION | WS_THICKFRAME))
        rc = data.rc
        user32.SetWindowPos(hwnd, wintypes.HWND(HWND_TOPMOST), rc.left, rc.top, rc.right - rc.left,
                            rc.bottom - rc.top, SWP_FRAMECHANGED | SWP_SHOWWINDOW)
        self.edge = edge
        return rc.left, rc.top, rc.right, rc.bottom

    def undock(self) -> None:
        """Give the screen strip back and restore the window's frame, size and place."""
        if self.edge is None:
            return
        user32, _, set_style = _user32()
        hwnd = wintypes.HWND(self.hwnd)
        _shell_message(ABM_REMOVE, self._data())
        self.edge = None
        if self._saved:
            style, (left, top, right, bottom), maximized = self._saved
            set_style(hwnd, GWL_STYLE, style)
            user32.SetWindowPos(hwnd, wintypes.HWND(HWND_NOTOPMOST), left, top, right - left, bottom - top,
                                SWP_FRAMECHANGED | SWP_SHOWWINDOW)
            if maximized:
                user32.ShowWindow(hwnd, SW_MAXIMIZE)
