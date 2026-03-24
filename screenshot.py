import tkinter as tk
from PIL import ImageGrab
import platform

if platform.system() == "Windows":
    import ctypes

# TODO fix laptop trackpad
class Screenshot:
    def __init__(self, root):
        self.root = root

        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.3)
        self.root.configure(bg='black')

        self.start_x = None
        self.start_y = None
        self.curr_x = None
        self.curr_y = None

        self.rect = None
        self.screenshot = None

        self.canvas = tk.Canvas(root, cursor="cross", bg="grey11")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        self.root.bind("<Key>", lambda x: self.root.destroy())

        self.label = tk.Label(
            self.canvas,
            text=' Select reigon to screenshot or press any key to exit... ',
            font=("Arial", 16), 
        )
        self.label.pack(pady=10)

    def on_button_press(self, event):
        self.start_x = event.x
        self.start_y = event.y

        self.rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y, 
            outline='red',
            width=2
        )

    def on_mouse_drag(self, event):
        self.curr_x, self.curr_y = (event.x, event.y)
        self.canvas.coords(self.rect, self.start_x, self.start_y, self.curr_x, self.curr_y)

    def on_button_release(self, event):
        if None in (self.start_x, self.start_y, self.curr_x, self.curr_y):
            return

        bbox=(
            min(self.start_x, self.curr_x),
            min(self.start_y, self.curr_y),
            max(self.start_x, self.curr_x),
            max(self.start_y, self.curr_y)
        )
        
        self.screenshot = ImageGrab.grab(bbox=bbox)
        self.root.destroy()

def minimize() -> None:
    '''minimize console window'''
    if platform.system() == "Windows":
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 6)

def restore() -> None:
    '''restore console window'''
    if platform.system() == "Windows":
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 9)

def get_screenshot(filename: str) -> None:
    minimize()
    root = tk.Tk()
    app = Screenshot(root)
    root.mainloop()
    restore()
    assert app.screenshot is not None
    app.screenshot.save(filename)