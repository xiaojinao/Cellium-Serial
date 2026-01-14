# -*- coding: utf-8 -*-
"""
标题栏处理器
封装窗口控制操作，提供统一的 API 供前端调用

支持的系统命令：
- titlebar:minimize    -> 最小化窗口
- titlebar:maximize    -> 最大化/还原窗口
- titlebar:close       -> 关闭窗口
- titlebar:restore     -> 还原窗口
- titlebar:minimize    -> 最小化窗口
- titlebar:show        -> 显示窗口
- titlebar:hide        -> 隐藏窗口
- titlebar:setTitle    -> 设置窗口标题
- titlebar:startDrag   -> 开始拖动窗口（用于自定义拖动区域）
- titlebar:flash       -> 闪烁窗口任务栏按钮
- titlebar:setAlwaysOnTop -> 设置窗口置顶状态
- titlebar:getState    -> 获取窗口状态

"""

import ctypes
import logging
from typing import Optional, Callable, Any
from ..bus.event_bus import event_bus, event
from ..bus.events import EventType
from ..interface.icell import ICell

user32 = ctypes.windll.user32
byref = ctypes.byref
logger = logging.getLogger(__name__)


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_uint),
        ("flags", ctypes.c_uint),
        ("showCmd", ctypes.c_uint),
        ("ptMinPosition", ctypes.wintypes.POINT),
        ("ptMaxPosition", ctypes.wintypes.POINT),
        ("rcNormalPosition", ctypes.wintypes.RECT),
    ]


class TitleBarHandler:
    """标题栏处理器 - 封装窗口控制操作"""
    
    # 窗口状态常量
    STATE_NORMAL = 1
    STATE_MINIMIZED = 2
    STATE_MAXIMIZED = 3
    
    def __init__(self, hwnd: int):
        self.hwnd = hwnd
        self._is_maximized = False
        self._always_on_top = False
        logger.info(f"标题栏处理器已初始化，HWND: {hwnd}")
    
    def minimize(self) -> str:
        """最小化窗口"""
        try:
            user32.ShowWindow(self.hwnd, 2)
            logger.info("窗口已最小化")
            return "OK"
        except Exception as e:
            logger.error(f"最小化窗口失败: {e}")
            return f"Error: {str(e)}"
    
    def maximize(self) -> str:
        """最大化窗口"""
        try:
            user32.ShowWindow(self.hwnd, 3)
            self._is_maximized = True
            logger.info("窗口已最大化")
            return "OK"
        except Exception as e:
            logger.error(f"最大化窗口失败: {e}")
            return f"Error: {str(e)}"
    
    def restore(self) -> str:
        """还原窗口"""
        try:
            user32.ShowWindow(self.hwnd, 9)
            self._is_maximized = False
            logger.info("窗口已还原")
            return "OK"
        except Exception as e:
            logger.error(f"还原窗口失败: {e}")
            return f"Error: {str(e)}"
    
    def toggle_maximize(self) -> str:
        """切换最大化/还原状态"""
        try:
            placement = WINDOWPLACEMENT()
            placement.length = ctypes.sizeof(WINDOWPLACEMENT)
            user32.GetWindowPlacement(self.hwnd, byref(placement))
            
            show_cmd = placement.showCmd
            is_currently_maximized = (show_cmd == 3)
            
            if is_currently_maximized:
                self._is_maximized = False
                user32.ShowWindow(self.hwnd, 9)
                logger.info("窗口已还原")
            else:
                self._is_maximized = True
                user32.ShowWindow(self.hwnd, 3)
                logger.info("窗口已最大化")
            return "OK"
        except Exception as e:
            logger.error(f"切换窗口状态失败: {e}")
            return f"Error: {str(e)}"
    
    def close(self, force: bool = False) -> str:
        """关闭窗口
        
        Args:
            force: 是否强制关闭（忽略淡出动画）
        """
        try:
            if force:
                user32.DestroyWindow(self.hwnd)
                logger.info("窗口已强制关闭")
            else:
                event_bus.publish(EventType.FADE_OUT)
                logger.info("触发窗口关闭动画")
            return "OK"
        except Exception as e:
            logger.error(f"关闭窗口失败: {e}")
            return f"Error: {str(e)}"
    
    def show(self) -> str:
        """显示窗口"""
        try:
            user32.ShowWindow(self.hwnd, 5)
            user32.SetForegroundWindow(self.hwnd)
            logger.info("窗口已显示")
            return "OK"
        except Exception as e:
            logger.error("显示窗口失败: {e}")
            return f"Error: {str(e)}"
    
    def hide(self) -> str:
        """隐藏窗口"""
        try:
            user32.ShowWindow(self.hwnd, 0)
            logger.info("窗口已隐藏")
            return "OK"
        except Exception as e:
            logger.error(f"隐藏窗口失败: {e}")
            return f"Error: {str(e)}"
    
    def set_title(self, title: str) -> str:
        """设置窗口标题
        
        Args:
            title: 新的窗口标题
        """
        try:
            user32.SetWindowTextW(self.hwnd, title)
            logger.info(f"窗口标题已设置为: {title}")
            return "OK"
        except Exception as e:
            logger.error(f"设置窗口标题失败: {e}")
            return f"Error: {str(e)}"
    
    def get_title(self) -> str:
        """获取当前窗口标题"""
        try:
            title_length = user32.GetWindowTextLengthW(self.hwnd)
            if title_length > 0:
                buffer = ctypes.create_unicode_buffer(title_length + 1)
                user32.GetWindowTextW(self.hwnd, buffer, title_length + 1)
                return buffer.value
            return ""
        except Exception as e:
            logger.error(f"获取窗口标题失败: {e}")
            return ""
    
    def start_drag(self) -> str:
        """开始拖动窗口
        
        用于前端自定义拖动区域，在 mousedown 时调用
        """
        try:
            user32.ReleaseCapture()
            user32.SendMessageW(self.hwnd, 0xA1, 2, 0)
            logger.info("开始拖动窗口")
            return "OK"
        except Exception as e:
            logger.error(f"拖动窗口失败: {e}")
            return f"Error: {str(e)}"
    
    def flash(self, invert: bool = False) -> str:
        """闪烁窗口任务栏按钮
        
        Args:
            invert: 是否反色闪烁
        """
        try:
            FLASHW_STOP = 0
            FLASHW_CAPTION = 1
            FLASHW_TRAY = 2
            FLASHW_ALL = 3
            FLASHW_TIMER = 4
            FLASHW_TIMERNOFG = 12
            
            count = 5 if not invert else 1
            
            class FLASHWINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_uint),
                    ("hwnd", ctypes.c_void_p),
                    ("dwFlags", ctypes.c_uint),
                    ("uCount", ctypes.c_uint),
                    ("dwTimeout", ctypes.c_uint),
                ]
            
            info = FLASHWINFO()
            info.cbSize = ctypes.sizeof(FLASHWINFO)
            info.hwnd = self.hwnd
            info.dwFlags = FLASHW_ALL | FLASHW_TIMER
            info.uCount = count
            info.dwTimeout = 0
            
            user32.FlashWindowEx(byref(info))
            logger.info("窗口已闪烁")
            return "OK"
        except Exception as e:
            logger.error(f"闪烁窗口失败: {e}")
            return f"Error: {str(e)}"
    
    def set_always_on_top(self, enable: bool) -> str:
        """设置窗口置顶状态
        
        Args:
            enable: True 为置顶，False 为取消置顶
        """
        try:
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_SHOWWINDOW = 0x0040
            
            hwnd_insert = HWND_TOPMOST if enable else HWND_NOTOPMOST
            user32.SetWindowPos(self.hwnd, hwnd_insert, 0, 0, 0, 0,
                              SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW)
            
            self._always_on_top = enable
            status = "置顶" if enable else "取消置顶"
            logger.info(f"窗口已{status}")
            return "OK"
        except Exception as e:
            logger.error(f"设置置顶状态失败: {e}")
            return f"Error: {str(e)}"
    
    def get_state(self) -> dict:
        """获取窗口当前状态
        
        Returns:
            dict: 包含窗口状态的字典
        """
        try:
            placement = WINDOWPLACEMENT()
            placement.length = ctypes.sizeof(WINDOWPLACEMENT)
            user32.GetWindowPlacement(self.hwnd, byref(placement))
            
            show_cmd = placement.showCmd
            state = "normal"
            if show_cmd == 2:
                state = "minimized"
            elif show_cmd == 3:
                state = "maximized"
            elif show_cmd == 9:
                state = "restored"
            
            return {
                "state": state,
                "isMaximized": state == "maximized",
                "isMinimized": state == "minimized",
                "isAlwaysOnTop": self._always_on_top,
                "title": self.get_title()
            }
        except Exception as e:
            logger.error(f"获取窗口状态失败: {e}")
            return {"state": "error", "error": str(e)}
    
    def resize(self, width: int, height: int) -> str:
        """调整窗口大小
        
        Args:
            width: 新的宽度
            height: 新的高度
        """
        try:
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_FRAMECHANGED = 0x0020
            
            user32.SetWindowPos(self.hwnd, None, 0, 0, width, height,
                              SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED)
            logger.info(f"窗口大小已调整为: {width}x{height}")
            return "OK"
        except Exception as e:
            logger.error(f"调整窗口大小失败: {e}")
            return f"Error: {str(e)}"
    
    def move(self, x: int, y: int) -> str:
        """移动窗口位置
        
        Args:
            x: 新的 X 坐标
            y: 新的 Y 坐标
        """
        try:
            SWP_NOSIZE = 0x0001
            SWP_NOZORDER = 0x0004
            SWP_FRAMECHANGED = 0x0020
            
            user32.SetWindowPos(self.hwnd, None, x, y, 0, 0,
                              SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED)
            logger.info(f"窗口位置已移动到: ({x}, {y})")
            return "OK"
        except Exception as e:
            logger.error(f"移动窗口失败: {e}")
            return f"Error: {str(e)}"
    
    def center(self) -> str:
        """将窗口居中显示"""
        try:
            screen_width = user32.GetSystemMetrics(0)
            screen_height = user32.GetSystemMetrics(1)
            
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(self.hwnd, byref(rect))
            
            window_width = rect.right - rect.left
            window_height = rect.bottom - rect.top
            
            x = (screen_width - window_width) // 2
            y = (screen_height - window_height) // 2
            
            return self.move(x, y)
        except Exception as e:
            logger.error(f"窗口居中失败: {e}")
            return f"Error: {str(e)}"
    
    def execute(self, command: str, *args) -> Any:
        """执行命令
        
        用于 ICell 接口兼容
        
        Args:
            command: 命令名称
            args: 命令参数
            
        Returns:
            命令执行结果
        """
        if command == "minimize":
            return self.minimize()
        elif command == "maximize":
            return self.maximize()
        elif command == "restore":
            return self.restore()
        elif command == "toggle":
            return self.toggle_maximize()
        elif command == "close":
            return self.close()
        elif command == "show":
            return self.show()
        elif command == "hide":
            return self.hide()
        elif command == "setTitle":
            title = args[0] if args else ""
            return self.set_title(title)
        elif command == "startDrag":
            return self.start_drag()
        elif command == "flash":
            return self.flash()
        elif command == "setAlwaysOnTop":
            enable = args[0].lower() == "true" if args else True
            return self.set_always_on_top(enable)
        elif command == "getState":
            return self.get_state()
        elif command == "resize":
            width = int(args[0]) if args else 800
            height = int(args[1]) if len(args) > 1 else 600
            return self.resize(width, height)
        elif command == "move":
            x = int(args[0]) if args else 0
            y = int(args[1]) if len(args) > 1 else 0
            return self.move(x, y)
        elif command == "center":
            return self.center()
        else:
            logger.warning(f"未知命令: {command}")
            return f"Error: Unknown command '{command}'"


class TitleBarCell(ICell):
    """标题栏组件 - 可注册到组件系统的标题栏处理器"""
    
    def __init__(self, hwnd: int):
        super().__init__()
        self.name = "titlebar"
        self.handler = TitleBarHandler(hwnd)
        logger.info("标题栏组件已初始化")
    
    @event("titlebar.minimize")
    def on_minimize(self):
        """监听最小化事件"""
        return self.handler.minimize()
    
    @event("titlebar.maximize")
    def on_maximize(self):
        """监听最大化事件"""
        return self.handler.maximize()
    
    @event("titlebar.close")
    def on_close(self):
        """监听关闭事件"""
        return self.handler.close()
    
    def execute(self, command: str, *args) -> Any:
        """执行标题栏命令"""
        return self.handler.execute(command, *args)
    
    def get_handler(self) -> TitleBarHandler:
        """获取标题栏处理器"""
        return self.handler


_handler_instance: Optional[TitleBarCell] = None


def get_titlebar_handler(hwnd: int) -> TitleBarCell:
    """获取标题栏处理器实例"""
    global _handler_instance
    if _handler_instance is None:
        _handler_instance = TitleBarCell(hwnd)
    return _handler_instance
