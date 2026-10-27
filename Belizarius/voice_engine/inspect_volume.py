
import time
import ctypes
from pywinauto.keyboard import send_keys
from pywinauto import Desktop

user32 = ctypes.windll.user32

# Open Quick Settings.
send_keys("{VK_LWIN down}a{VK_LWIN up}")
time.sleep(2)

# Inspect only the foreground window.
hwnd = user32.GetForegroundWindow()

if not hwnd:
    print("No foreground window detected.")
    raise SystemExit(1)

title_length = user32.GetWindowTextLengthW(hwnd)
title_buffer = ctypes.create_unicode_buffer(title_length + 1)
user32.GetWindowTextW(hwnd, title_buffer, title_length + 1)

print("Foreground window title:", repr(title_buffer.value))

try:
    window = Desktop(backend="uia").window(handle=hwnd)

    print("Slider controls in foreground window:")
    sliders = window.descendants(control_type="Slider")

    if not sliders:
        print("No accessible sliders found.")

    for slider in sliders:
        try:
            print(
                "Name:", repr(slider.window_text()),
                "| Type:", slider.element_info.control_type
            )
        except Exception:
            print("A slider exists, but its details could not be read.")

except Exception as exc:
    print("Could not inspect foreground window:", type(exc).__name__)
