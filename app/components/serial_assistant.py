# -*- coding: utf-8 -*-
"""
串口调试助手组件
提供串口通信功能，支持数据收发
"""

import logging
import threading
import serial
import serial.tools.list_ports
from typing import Dict, Any, Optional, List
from app.core.interface.icell import ICell
from app.core.di.container import injected, AutoInjectMeta
from app.core.bus.event_bus import event_bus, EventBus

logger = logging.getLogger(__name__)

BYTESIZE_MAP = {5: serial.FIVEBITS, 6: serial.SIXBITS, 7: serial.SEVENBITS, 8: serial.EIGHTBITS}
PARITY_MAP = {'N': serial.PARITY_NONE, 'O': serial.PARITY_ODD, 'E': serial.PARITY_EVEN, 'M': serial.PARITY_MARK, 'S': serial.PARITY_SPACE}
STOPBITS_MAP = {1: serial.STOPBITS_ONE, 1.5: serial.STOPBITS_ONE_POINT_FIVE, 2: serial.STOPBITS_TWO}


class SerialAssistantCell(ICell, metaclass=AutoInjectMeta):
    """
    串口调试助手组件

    功能：
    - 获取可用串口列表
    - 打开/关闭串口（支持完整参数配置）
    - 发送数据（字符串/HEX）
    - 接收数据（自动读取线程）
    """

    event_bus = injected(EventBus)

    @property
    def cell_name(self) -> str:
        return "serial_assistant"

    def execute(self, command: str, *args, **kwargs) -> Any:
        """命令分发"""
        try:
            if command == "list_ports":
                return self._list_ports()

            elif command == "open":
                params = args[0] if args else {}
                if isinstance(params, dict):
                    return self._open_port(**params)
                return self._open_port()

            elif command == "close":
                return self._close_port()

            elif command == "send":
                data = args[0] if args else ''
                if isinstance(data, dict):
                    data = data.get('data', '')
                return self._send_data(data)

            elif command == "send_hex":
                hex_data = args[0] if args else ''
                if isinstance(hex_data, dict):
                    hex_data = hex_data.get('hex', '')
                return self._send_hex(hex_data)

            elif command == "get_status":
                return self._get_status()

            return {"status": "error", "message": f"Unknown command: {command}"}
        except Exception as e:
            logger.error(f"串口命令执行失败: {e}")
            return {"status": "error", "message": str(e)}

    def get_commands(self) -> dict:
        return {
            "list_ports": "获取可用串口列表",
            "open": "打开串口 (参数: port, baudrate, bytesize, parity, stopbits, rtscts, xonxoff)",
            "close": "关闭当前串口",
            "send": "发送字符串数据",
            "send_hex": "发送十六进制数据",
            "get_status": "获取串口状态"
        }

    def __init__(self):
        self._serial_port: Optional[serial.Serial] = None
        self._read_thread: Optional[threading.Thread] = None
        self._running = False
        self._received_data: List[str] = []
        self._sent_data: List[str] = []
        self._lock = threading.Lock()
        self._current_params: Dict[str, Any] = {}

    def _list_ports(self) -> Dict[str, Any]:
        """获取可用串口列表"""
        ports = serial.tools.list_ports.comports()
        port_list = []
        for port in ports:
            port_list.append({
                "device": port.device,
                "description": port.description,
                "hwid": port.hwid
            })
        logger.info(f"发现 {len(port_list)} 个串口")
        return {"status": "success", "ports": port_list}

    def _open_port(self, port: str = '', baudrate: int = 9600, bytesize: int = 8,
                   parity: Optional[str] = None, stopbits: float = 1,
                   rtscts: bool = False, xonxoff: bool = False) -> Dict[str, Any]:
        """打开串口（支持完整参数配置）"""
        if self._serial_port and self._serial_port.is_open:
            self._close_port()

        if not port:
            return {"status": "error", "message": "未指定串口号"}

        try:
            serial_bytesize = BYTESIZE_MAP.get(bytesize, serial.EIGHTBITS)
            serial_parity = PARITY_MAP.get(parity.upper() if parity else 'N', serial.PARITY_NONE)
            serial_stopbits = STOPBITS_MAP.get(stopbits, serial.STOPBITS_ONE)

            self._serial_port = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=serial_bytesize,
                parity=serial_parity,
                stopbits=serial_stopbits,
                timeout=0.1,
                write_timeout=1,
                rtscts=rtscts,
                xonxoff=xonxoff
            )

            self._current_params = {
                'port': port,
                'baudrate': baudrate,
                'bytesize': bytesize,
                'parity': parity.upper() if parity else 'None',
                'stopbits': stopbits,
                'rtscts': rtscts,
                'xonxoff': xonxoff
            }

            self._running = True
            self._start_read_thread()

            logger.info(f"串口已打开: {port}, 波特率: {baudrate}, 数据位: {bytesize}, 校验: {parity}, 停止位: {stopbits}")
            event_bus.publish("serial.opened", **self._current_params)

            return {
                "status": "success",
                "message": f"串口已打开: {port}",
                "port": port,
                "baudrate": baudrate,
                "bytesize": bytesize,
                "parity": parity,
                "stopbits": stopbits
            }
        except Exception as e:
            error_msg = f"打开串口失败: {e}"
            logger.error(error_msg)
            return {"status": "error", "message": error_msg}

    def _close_port(self) -> Dict[str, Any]:
        """关闭串口"""
        self._running = False

        if self._read_thread and self._read_thread.is_alive():
            self._read_thread.join(timeout=1)

        if self._serial_port and self._serial_port.is_open:
            self._serial_port.close()
            self._serial_port = None

        logger.info("串口已关闭")
        event_bus.publish("serial.closed")

        return {"status": "success", "message": "串口已关闭"}

    def _start_read_thread(self):
        """启动数据读取线程"""
        self._read_thread = threading.Thread(target=self._read_data, daemon=True)
        self._read_thread.start()

    def _read_data(self):
        """后台读取串口数据"""
        while self._running and self._serial_port and self._serial_port.is_open:
            try:
                if self._serial_port.in_waiting > 0:
                    data = self._serial_port.read(self._serial_port.in_waiting)
                    with self._lock:
                        data_str = data.decode('utf-8', errors='replace')
                        self._received_data.append(data_str)

                    logger.debug(f"收到数据: {data_str[:100]}")
                    event_bus.publish("serial.data_received", data=data_str)

            except Exception as e:
                logger.error(f"读取串口数据错误: {e}")
                break

    def _send_data(self, data: str) -> Dict[str, Any]:
        """发送字符串数据"""
        if not self._serial_port or not self._serial_port.is_open:
            return {"status": "error", "message": "串口未打开"}

        try:
            self._serial_port.write(data.encode('utf-8'))
            with self._lock:
                self._sent_data.append(data)

            logger.debug(f"发送数据: {data[:100]}")
            event_bus.publish("serial.data_sent", data=data)

            return {"status": "success", "message": "数据已发送", "length": len(data)}
        except Exception as e:
            error_msg = f"发送数据失败: {e}"
            logger.error(error_msg)
            return {"status": "error", "message": error_msg}

    def _send_hex(self, hex_data: str) -> Dict[str, Any]:
        """发送十六进制数据"""
        if not self._serial_port or not self._serial_port.is_open:
            return {"status": "error", "message": "串口未打开"}

        try:
            data_bytes = bytes.fromhex(hex_data.replace(' ', ''))
            self._serial_port.write(data_bytes)

            with self._lock:
                self._sent_data.append(hex_data)

            logger.debug(f"发送十六进制: {hex_data}")
            event_bus.publish("serial.data_sent", data=hex_data, hex=True)

            return {"status": "success", "message": "十六进制数据已发送", "length": len(data_bytes)}
        except Exception as e:
            error_msg = f"发送十六进制失败: {e}"
            logger.error(error_msg)
            return {"status": "error", "message": error_msg}

    def _get_status(self) -> Dict[str, Any]:
        """获取串口状态"""
        is_open = bool(self._serial_port and self._serial_port.is_open)

        return {
            "status": "success",
            "is_open": is_open,
            "port": self._serial_port.port if self._serial_port else None,
            "baudrate": self._serial_port.baudrate if self._serial_port else None,
            "received_count": len(self._received_data),
            "sent_count": len(self._sent_data)
        }

    def get_received_data(self) -> str:
        """获取所有已接收数据"""
        with self._lock:
            return ''.join(self._received_data)

    def clear_received_data(self):
        """清空接收缓冲区"""
        with self._lock:
            self._received_data.clear()

    def get_sent_data(self) -> str:
        """获取所有已发送数据"""
        with self._lock:
            return ''.join(self._sent_data)
