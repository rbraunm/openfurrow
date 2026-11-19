# SPDX-License-Identifier: Apache-2.0
"""What the Windows service manager starts for an OpenFurrow service: this file, run by its path.

It connects to the service manager at once, on the standard library alone, and loads
OpenFurrow only then. A new service process has thirty seconds to connect, and
OpenFurrow's first import on a small machine just started can take a good part of
that; once connected, the service says "start pending" and takes the time it needs.
Whatever goes wrong before OpenFurrow's own log is open (a broken installation, a
definition it cannot read) is written to the Windows application event log under the
service's name, and the service stops with the service-specific exit code 2.

In a console, run `python -m openfurrow.osService.host` instead.
"""

import ctypes
import sys
import traceback
from ctypes import wintypes

serviceWin32OwnProcess = 0x10
stateStopped, stateStartPending = 1, 2
controlInterrogate = 4
noError, errorCallNotImplemented, errorServiceSpecificError = 0, 120, 1066
loadSeconds = 120
loadFailedExitCode = 2
eventlogErrorType = 1
consoleLogoffEvent, consoleShutdownEvent = 5, 6


class SERVICE_STATUS(ctypes.Structure):
  _fields_ = [("dwServiceType", wintypes.DWORD), ("dwCurrentState", wintypes.DWORD),
              ("dwControlsAccepted", wintypes.DWORD), ("dwWin32ExitCode", wintypes.DWORD),
              ("dwServiceSpecificExitCode", wintypes.DWORD), ("dwCheckPoint", wintypes.DWORD),
              ("dwWaitHint", wintypes.DWORD)]


class Connection:
  """One service's side of the service manager's protocol: the dispatcher, the control handler and the status calls."""

  def __init__(self, arguments: list[str]) -> None:
    self.arguments = arguments
    self.exitCode = loadFailedExitCode
    self.answerControl = None
    self.statusHandle = None
    self.advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    self.serviceMainType = ctypes.WINFUNCTYPE(None, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR))
    self.handlerType = ctypes.WINFUNCTYPE(wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.LPVOID)
    self.advapi32.RegisterServiceCtrlHandlerExW.argtypes = (wintypes.LPCWSTR, self.handlerType, wintypes.LPVOID)
    self.advapi32.RegisterServiceCtrlHandlerExW.restype = wintypes.HANDLE
    self.advapi32.SetServiceStatus.argtypes = (wintypes.HANDLE, ctypes.POINTER(SERVICE_STATUS))
    self.advapi32.SetServiceStatus.restype = wintypes.BOOL
    self.advapi32.RegisterEventSourceW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
    self.advapi32.RegisterEventSourceW.restype = wintypes.HANDLE
    self.advapi32.ReportEventW.argtypes = (wintypes.HANDLE, wintypes.WORD, wintypes.WORD, wintypes.DWORD, wintypes.LPVOID,
                                           wintypes.WORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPCWSTR), wintypes.LPVOID)
    self.advapi32.ReportEventW.restype = wintypes.BOOL
    self.advapi32.DeregisterEventSource.argtypes = (wintypes.HANDLE,)
    self.serviceMain = self.serviceMainType(self._serviceMain)
    self.handler = self.handlerType(self._handler)
    # Started through a virtual environment's python.exe the process has a console of its own, and Windows ends
    # a console process that leaves a logoff or shutdown event unanswered. The service manager's controls stop
    # this one.
    consoleHandlerType = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
    self.consoleHandler = consoleHandlerType(lambda event: event in (consoleLogoffEvent, consoleShutdownEvent))
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetConsoleCtrlHandler.argtypes = (consoleHandlerType, wintypes.BOOL)
    kernel32.SetConsoleCtrlHandler(self.consoleHandler, True)

  def dispatch(self) -> int:
    """Hand this thread to the service manager until the service has stopped; the process's exit code."""

    class SERVICE_TABLE_ENTRYW(ctypes.Structure):
      _fields_ = [("lpServiceName", wintypes.LPWSTR), ("lpServiceProc", self.serviceMainType)]

    table = (SERVICE_TABLE_ENTRYW * 2)()
    table[0].lpServiceName = ""
    table[0].lpServiceProc = self.serviceMain
    self.advapi32.StartServiceCtrlDispatcherW.argtypes = (ctypes.POINTER(SERVICE_TABLE_ENTRYW),)
    self.advapi32.StartServiceCtrlDispatcherW.restype = wintypes.BOOL
    if not self.advapi32.StartServiceCtrlDispatcherW(table):
      print(f"no service manager started this process ({ctypes.FormatError(ctypes.get_last_error()).strip()}); "
            f"in a console, run python -m openfurrow.osService.host", file=sys.stderr)
      return 1
    return self.exitCode

  def setStatus(self, status) -> None:
    value = SERVICE_STATUS(serviceWin32OwnProcess, status.currentState, status.controlsAccepted, status.win32ExitCode,
                           status.serviceSpecificExitCode, status.checkPoint, status.waitHint)
    if not self.advapi32.SetServiceStatus(self.statusHandle, ctypes.byref(value)):
      raise ctypes.WinError(ctypes.get_last_error())

  def _setRawStatus(self, state: int, exitCode: int, checkPoint: int, waitHint: int) -> None:
    win32ExitCode = errorServiceSpecificError if exitCode else noError
    value = SERVICE_STATUS(serviceWin32OwnProcess, state, 0, win32ExitCode, exitCode, checkPoint, waitHint)
    self.advapi32.SetServiceStatus(self.statusHandle, ctypes.byref(value))

  def _handler(self, control, eventType, eventData, context) -> int:
    try:
      if self.answerControl is not None:
        return self.answerControl(control)
      return noError if control == controlInterrogate else errorCallNotImplemented
    except BaseException:
      return errorCallNotImplemented

  def _serviceMain(self, argumentCount, serviceArguments) -> None:
    name = serviceArguments[0]
    self.statusHandle = self.advapi32.RegisterServiceCtrlHandlerExW(name, self.handler, None)
    if not self.statusHandle:
      self._writeEvent(name, f"the control handler could not be registered: Windows error {ctypes.get_last_error()}")
      return
    self._setRawStatus(stateStartPending, 0, 1, loadSeconds * 1000)
    try:
      from openfurrow.osService import windowsHost
      self.exitCode = windowsHost.serve(self.arguments, self.setStatus, self._takeControls)
    except BaseException:
      self._writeEvent(name, traceback.format_exc())
      self._setRawStatus(stateStopped, loadFailedExitCode, 0, 0)

  def _takeControls(self, answerControl) -> None:
    self.answerControl = answerControl

  def _writeEvent(self, source: str, text: str) -> None:
    log = self.advapi32.RegisterEventSourceW(None, source)
    if log:
      self.advapi32.ReportEventW(log, eventlogErrorType, 0, 1, None, 1, 0, (wintypes.LPCWSTR * 1)(text), None)
      self.advapi32.DeregisterEventSource(log)


if __name__ == "__main__":
  sys.exit(Connection(sys.argv[1:]).dispatch())
