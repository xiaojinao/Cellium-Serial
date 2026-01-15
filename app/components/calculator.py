# -*- coding: utf-8 -*-
"""
Cellium 组件模块

通过继承 ICell 接口并使用 AutoInjectMeta 元类定义组件。
支持事件驱动模式进行组件间通信。
"""

import logging
import re
from app.core.di.container import injected, AutoInjectMeta
from app.core.interface.icell import ICell
from app.core.bus import event, event_bus, register_component_handlers

logger = logging.getLogger(__name__)


def _sanitize_expression(expression: str) -> str:
    allowed_chars = set('0123456789+-*/.() ')
    sanitized = ''.join(c if c in allowed_chars else '' for c in expression)
    return sanitized


def _calculate_impl(expression: str) -> str:
    sanitized = _sanitize_expression(expression)
    result = eval(sanitized)
    return str(result)


# ============================================================================
# Cellium 组件定义
# ============================================================================
# Cellium 是一个轻量级组件框架，提供以下核心特性：
# 1. ICell 接口 - 所有组件必须实现的标准接口
# 2. AutoInjectMeta 元类 - 自动解析 injected 声明的依赖
# 3. DI 容器 - 单例管理，自动注入依赖
# 4. 事件驱动模式 - 使用 @event 装饰器声明事件处理器
# 5. 统一命令模式 - 组件通过 execute() 方法响应前端命令
# ============================================================================


class Calculator(ICell, metaclass=AutoInjectMeta):
    """
    Cellium 组件定义示例
    
    Cellium 特性使用说明：
    
    1. 继承 ICell 接口
       - 必须实现 cell_name 属性（组件唯一标识）
       - 必须实现 execute() 方法（处理前端命令）
       - 可选实现 get_commands()（声明支持的命令）
    
    2. 使用 AutoInjectMeta 元类
       - 自动解析类属性中的 injected() 声明
       - 自动从 DI 容器获取依赖实例并注入
       - 无需手动调用容器或编写 __init__ 注入逻辑
    
    3. 事件驱动模式
       - 使用 @event(事件名) 装饰器声明事件处理器
       - 使用 register_component_handlers(self) 自动注册处理器
       - 使用 event_bus.publish(事件名, **kwargs) 发布事件
       - 支持组件间解耦通信，无需直接引用
    
    4. 依赖注入声明
       - 使用 injected(依赖类型) 声明需要的依赖
       - 运行时自动从容器获取单例并注入
       - 支持跨组件共享状态和资源
    
    5. 组件注册与发现
       - 组件通过 ICell 接口被 DI 容器管理
       - 前端通过 cell_name 标识调用对应组件
       - 支持热拔插和动态组件加载
    """
    
    _warmed_up = False
    
    def __init__(self):
        register_component_handlers(self)
    
    @event("calc.requested")
    def on_calc_requested(self, event_name, **kwargs):
        """计算请求事件处理器"""
        expression = kwargs.get('expression', '')
        logger.info(f"[事件] 收到计算请求: {expression}")
    
    @event("calc.completed")
    def on_calc_completed(self, event_name, **kwargs):
        """计算完成事件处理器"""
        expression = kwargs.get('expression', '')
        result = kwargs.get('result', '')
        logger.info(f"[事件] 计算完成: {expression} = {result}")
    
    @event("calc.error")
    def on_calc_error(self, event_name, **kwargs):
        """计算错误事件处理器"""
        expression = kwargs.get('expression', '')
        error = kwargs.get('error', '')
        logger.error(f"[事件] 计算错误: {expression} - {error}")
    
    # =========================================================================
    # ICell 接口实现
    # =========================================================================
    
    @property
    def cell_name(self) -> str:
        """返回组件唯一标识
        
        Returns:
            str: 组件名称，前端通过此名称调用组件
                 例如：pycmd('calculator:calc:1+1')
        """
        return "calculator"
    
    def execute(self, command: str, *args, **kwargs) -> str:
        """执行组件命令（ICell 接口核心方法）
        
        Cellium 命令分发机制：
        1. 前端发送 pycmd('组件名:命令:参数')
        2. 框架解析并路由到对应组件的 execute()
        3. execute() 根据 command 参数分发到具体处理方法
        
        Args:
            command: 命令名称（框架从命令字符串中提取）
            *args: 命令参数
            **kwargs: 关键字参数
            
        Returns:
            str: 命令执行结果，返回给前端 JavaScript
        """
        expression = args[0] if args else ''
        
        if command in ("calc", "eval"):
            return self.calculate(expression)
        else:
            return f"Error: Unknown command '{command}'"
    
    def get_commands(self) -> dict:
        """返回组件支持的命令列表（可选）
        
        Returns:
            dict: 命令名到描述的映射，用于前端命令自动补全和文档
        """
        return {
            "calc": "计算表达式，例如: calculator:calc:1+1",
            "eval": "计算表达式（与 calc 相同），例如: calculator:eval:2*3"
        }
    
    # =========================================================================
    # 属性注入（框架自动调用）
    # =========================================================================
    
    @property
    def webview(self):
        return self._webview
    
    @webview.setter
    def webview(self, value):
        self._webview = value
    
    @property
    def lib(self):
        return self._lib
    
    @lib.setter
    def lib(self, value):
        self._lib = value

    @property
    def bridge(self):
        return self._bridge

    @bridge.setter
    def bridge(self, value):
        self._bridge = value
    
    def calculate(self, expression: str) -> str:
        event_bus.publish("calc.requested", expression=expression)
        try:
            result = _calculate_impl(expression)
            event_bus.publish("calc.completed", expression=expression, result=result)
            return result
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            event_bus.publish("calc.error", expression=expression, error=error_msg)
            return error_msg
    
    def handle_calc_query(self, webview, query_id, custom_msg, expression):
        result = self.calculate(expression)
        logger.info(f"[INFO] 计算结果: {result}")
        return result
    
    def show_result(self, result: str):
        self.bridge.set_element_value('calc-display', result)
    
    def handle_calc_result(self, result: str):
        self.show_result(result)
