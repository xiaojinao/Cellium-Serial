# -*- coding: utf-8 -*-
"""
串口调试助手组件
提供串口通信功能，支持数据收发
"""

import json
import logging
import threading
import time
import serial
import serial.tools.list_ports
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Dict, Any, Optional, List, Tuple
from app.core.interface.icell import ICell
from app.core.di.container import injected, AutoInjectMeta
from app.core.bus.event_bus import event_bus, EventBus

logger = logging.getLogger(__name__)


class SSEServer:
    """轻量级SSE服务器，用于实时推送串口数据"""
    
    def __init__(self, host: str = 'localhost', port: int = 8080):
        self.host = host
        self.port = port
        self.clients: List = []
        self.lock = threading.Lock()
        self.server: Optional[HTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.running = False
        
    def start(self):
        """启动SSE服务器"""
        if self.running:
            return
            
        self.running = True
        self.server = SSEServerThreaded(self.host, self.port, self)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        logger.info(f"SSE服务器已启动: http://{self.host}:{self.port}/serial_stream")
        
    def stop(self):
        """停止SSE服务器"""
        self.running = False
        if self.server:
            try:
                self.server.socket.close()
            except Exception as e:
                logger.debug(f"关闭服务器socket失败: {e}")
        logger.info("SSE服务器已停止")
        
    def add_client(self, client_handler):
        """添加SSE客户端"""
        with self.lock:
            if client_handler not in self.clients:
                self.clients.append(client_handler)
        
    def remove_client(self, client_handler):
        """移除SSE客户端"""
        with self.lock:
            if client_handler in self.clients:
                self.clients.remove(client_handler)
        
    def broadcast(self, data: dict):
        """广播数据到所有客户端"""
        if not self.clients:
            return
            
        message = f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        message_bytes = message.encode('utf-8')
        
        with self.lock:
            current_clients = list(self.clients)
        
        for client in current_clients:
            try:
                if client and client.wfile:
                    client.wfile.write(message_bytes)
                    client.wfile.flush()
            except Exception:
                try:
                    self.remove_client(client)
                except Exception:
                    pass


class SSEServerThreaded(ThreadingMixIn, HTTPServer):
    """真正的多线程HTTP服务器，支持并行处理多个连接"""
    daemon_threads = True
    allow_reuse_address = True
    
    def __init__(self, host: str, port: int, sse_server: 'SSEServer'):
        super().__init__((host, port), SSERequestHandler)
        self.sse_server = sse_server
    
    def serve_forever(self):
        """优雅启动服务器循环"""
        try:
            super().serve_forever()
        except (OSError, Exception):
            pass


class SSERequestHandler(BaseHTTPRequestHandler):
    """SSE请求处理器"""
    
    protocol_version = 'HTTP/1.1'
    
    def log_message(self, format, *args):
        """自定义日志格式"""
        logger.debug(f"SSE请求: {args[0]}")
        
    def do_GET(self):
        """处理GET请求"""
        if self.path == '/serial_stream':
            self._handle_sse()
        else:
            self._send_error_response()
            
    def _handle_sse(self):
        """处理SSE连接请求"""
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Keep-Alive', 'timeout=300')
        self.end_headers()
        
        sse_server = self.server.sse_server
        sse_server.add_client(self)
        
        heartbeat_interval = 10
        
        try:
            while sse_server.running:
                try:
                    self.wfile.write(b': heartbeat\n\n')
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
                time.sleep(heartbeat_interval)
        except Exception as e:
            logger.debug(f"SSE连接维护异常: {e}")
        finally:
            try:
                sse_server.remove_client(self)
            except Exception:
                pass
            
    def _send_error_response(self):
        """发送错误响应"""
        self.send_response(404)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Not Found')


# 全局SSE服务器实例（单例模式）
_sse_server_instance: Optional['SSEServer'] = None

def get_sse_server() -> 'SSEServer':
    """获取SSE服务器单例实例"""
    global _sse_server_instance
    if _sse_server_instance is None:
        _sse_server_instance = SSEServer()
    return _sse_server_instance


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

    def execute(self, command: str, *args, **kwargs) -> str:
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
            
            elif command == "receive":
                return self._receive_data()
            
            elif command == "receive_hex":
                return self._receive_hex()

            elif command == "start_sse":
                return self._start_sse()
            
            elif command == "stop_sse":
                return self._stop_sse()
            
            elif command == "get_sse_url":
                return self._get_sse_url()
            
            elif command == "ping":
                return self._ping()
            
            elif command == "remove_sse_client":
                return self._remove_sse_client()

            return json.dumps({"status": "error", "message": f"Unknown command: {command}"}, ensure_ascii=False)
        except Exception as e:
            logger.error(f"串口命令执行失败: {e}")
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

    def get_commands(self) -> dict:
        return {
            "list_ports": "获取可用串口列表",
            "open": "打开串口 (参数: port, baudrate, bytesize, parity, stopbits, rtscts, xonxoff)",
            "close": "关闭当前串口",
            "send": "发送字符串数据",
            "send_hex": "发送十六进制数据",
            "get_status": "获取串口状态",
            "receive": "接收数据（轮询模式，字符串）",
            "receive_hex": "接收数据（轮询模式，HEX）",
            "start_sse": "启动SSE服务器（实时推送模式）",
            "stop_sse": "停止SSE服务器",
            "get_sse_url": "获取SSE连接URL"
        }

    def __init__(self):
        self._serial_port: Optional[serial.Serial] = None
        self._read_thread: Optional[threading.Thread] = None
        self._running = False
        self._received_data: List[Tuple[float, str]] = []
        self._received_hex: List[Tuple[float, str]] = []
        self._sent_data: List[Tuple[float, str]] = []
        self._lock = threading.Lock()
        self._current_params: Dict[str, Any] = {}
        self._start_time: float = time.perf_counter()
        self._sse_enabled = False

    def _list_ports(self) -> str:
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
        return json.dumps({"status": "success", "ports": port_list}, ensure_ascii=False)

    def _open_port(self, port: str = '', baudrate: int = 9600, bytesize: int = 8,
                   parity: Optional[str] = None, stopbits: float = 1,
                   rtscts: bool = False, xonxoff: bool = False) -> str:
        """打开串口（支持完整参数配置）"""
        if self._serial_port and self._serial_port.is_open:
            self._close_port()

        if not port:
            return json.dumps({"status": "error", "message": "未指定串口号"}, ensure_ascii=False)

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

            return json.dumps({
                "status": "success",
                "message": f"串口已打开: {port}",
                "port": port,
                "baudrate": baudrate,
                "bytesize": bytesize,
                "parity": parity,
                "stopbits": stopbits
            }, ensure_ascii=False)
        except Exception as e:
            error_msg = f"打开串口失败: {e}"
            logger.error(error_msg)
            return json.dumps({"status": "error", "message": error_msg}, ensure_ascii=False)

    def _close_port(self) -> str:
        """关闭串口"""
        self._running = False

        if self._read_thread and self._read_thread.is_alive():
            self._read_thread.join(timeout=1)

        if self._serial_port and self._serial_port.is_open:
            self._serial_port.close()
            self._serial_port = None

        logger.info("串口已关闭")
        event_bus.publish("serial.closed")

        return json.dumps({"status": "success", "message": "串口已关闭"}, ensure_ascii=False)

    def _start_read_thread(self):
        """启动数据读取线程"""
        self._read_thread = threading.Thread(target=self._read_data, daemon=True)
        self._read_thread.start()

    def _read_data(self):
        """后台读取串口数据"""
        while self._running and self._serial_port and self._serial_port.is_open:
            try:
                if self._serial_port.in_waiting > 0:
                    timestamp = time.perf_counter()
                    data = self._serial_port.read(self._serial_port.in_waiting)
                    elapsed_ms = (timestamp - self._start_time) * 1000
                    
                    data_str = data.decode('utf-8', errors='replace')
                    hex_str = ' '.join(f'{b:02X}' for b in data)
                    
                    with self._lock:
                        self._received_data.append((timestamp, data_str))
                        self._received_hex.append((timestamp, hex_str))
                    
                    if self._sse_enabled:
                        try:
                            sse_server = get_sse_server()
                            if sse_server:
                                sse_server.broadcast({
                                    "type": "receive",
                                    "elapsed_ms": elapsed_ms,
                                    "data_str": data_str,
                                    "hex": hex_str
                                })
                        except Exception as sse_error:
                            logger.debug(f"SSE广播失败（不影响串口读取）: {sse_error}")
                    
                    logger.debug(f"收到数据: {data_str[:100]}")

            except Exception as e:
                logger.error(f"读取串口数据错误: {e}")
                time.sleep(0.1)  # 避免紧密循环
    
    def _send_data(self, data: str) -> str:
        """发送字符串数据"""
        if not self._serial_port or not self._serial_port.is_open:
            return json.dumps({"status": "error", "message": "串口未打开"}, ensure_ascii=False)

        try:
            timestamp = time.perf_counter()
            self._serial_port.write(data.encode('utf-8'))
            with self._lock:
                self._sent_data.append((timestamp, data))

            logger.debug(f"发送数据: {data[:100]}")
            event_bus.publish("serial.data_sent", data=data)

            return json.dumps({"status": "success", "message": "数据已发送", "length": len(data)}, ensure_ascii=False)
        except Exception as e:
            error_msg = f"发送数据失败: {e}"
            logger.error(error_msg)
            return json.dumps({"status": "error", "message": error_msg}, ensure_ascii=False)

    def _send_hex(self, hex_data: str) -> str:
        """发送十六进制数据"""
        if not self._serial_port or not self._serial_port.is_open:
            return json.dumps({"status": "error", "message": "串口未打开"}, ensure_ascii=False)

        try:
            timestamp = time.perf_counter()
            data_bytes = bytes.fromhex(hex_data.replace(' ', ''))
            self._serial_port.write(data_bytes)

            with self._lock:
                self._sent_data.append((timestamp, hex_data))

            logger.debug(f"发送十六进制: {hex_data}")
            event_bus.publish("serial.data_sent", data=hex_data, hex=True)

            return json.dumps({"status": "success", "message": "十六进制数据已发送", "length": len(data_bytes)}, ensure_ascii=False)
        except Exception as e:
            error_msg = f"发送十六进制失败: {e}"
            logger.error(error_msg)
            return json.dumps({"status": "error", "message": error_msg}, ensure_ascii=False)

    def _get_status(self) -> str:
        """获取串口状态"""
        is_open = bool(self._serial_port and self._serial_port.is_open)

        return json.dumps({
            "status": "success",
            "is_open": is_open,
            "port": self._serial_port.port if self._serial_port else None,
            "baudrate": self._serial_port.baudrate if self._serial_port else None,
            "received_count": len(self._received_data),
            "sent_count": len(self._sent_data)
        }, ensure_ascii=False)
    
    def _receive_data(self) -> str:
        """获取并清空已接收的数据"""
        base_time = time.time()
        with self._lock:
            data_list = []
            for timestamp, data_str in self._received_data:
                elapsed_ms = (timestamp - self._start_time) * 1000 if hasattr(self, '_start_time') and self._start_time else 0
                data_list.append({
                    "timestamp": timestamp,
                    "elapsed_ms": elapsed_ms,
                    "data": data_str
                })
            self._received_data = []
        
        return json.dumps({
            "status": "success",
            "data": data_list
        }, ensure_ascii=False)
    
    def _receive_hex(self) -> str:
        """获取并清空已接收的HEX数据"""
        with self._lock:
            data_list = []
            for timestamp, hex_str in self._received_hex:
                elapsed_ms = (timestamp - self._start_time) * 1000 if hasattr(self, '_start_time') and self._start_time else 0
                data_list.append({
                    "timestamp": timestamp,
                    "elapsed_ms": elapsed_ms,
                    "data": hex_str
                })
            self._received_hex = []
        
        return json.dumps({
            "status": "success",
            "data": data_list
        }, ensure_ascii=False)
    
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
    
    def _start_sse(self) -> str:
        """启动SSE服务器"""
        try:
            server = get_sse_server()
            server.start()
            self._sse_enabled = True
            logger.info("SSE模式已启用")
            return json.dumps({
                "status": "success",
                "message": "SSE服务器已启动",
                "url": f"http://{server.host}:{server.port}/serial_stream"
            }, ensure_ascii=False)
        except Exception as e:
            error_msg = f"启动SSE服务器失败: {e}"
            logger.error(error_msg)
            return json.dumps({"status": "error", "message": error_msg}, ensure_ascii=False)
    
    def _stop_sse(self) -> str:
        """停止SSE服务器"""
        try:
            self._sse_enabled = False
            get_sse_server().stop()
            logger.info("SSE模式已禁用")
            return json.dumps({"status": "success", "message": "SSE服务器已停止"}, ensure_ascii=False)
        except Exception as e:
            error_msg = f"停止SSE服务器失败: {e}"
            logger.error(error_msg)
            return json.dumps({"status": "error", "message": error_msg}, ensure_ascii=False)
    
    def _get_sse_url(self) -> str:
        """获取SSE连接URL"""
        server = get_sse_server()
        if not self._sse_enabled or not server.running:
            return json.dumps({
                "status": "error",
                "message": "SSE服务器未启动"
            }, ensure_ascii=False)
        return json.dumps({
            "status": "success",
            "url": f"http://{server.host}:{server.port}/serial_stream",
            "enabled": self._sse_enabled
        }, ensure_ascii=False)
    
    def _ping(self) -> str:
        """前端心跳保持连接"""
        return json.dumps({"status": "success", "message": "pong"}, ensure_ascii=False)
    
    def _remove_sse_client(self) -> str:
        """前端通知移除无效客户端"""
        try:
            server = get_sse_server()
            server.clients.clear()
            logger.info("已清空SSE客户端列表")
            return json.dumps({"status": "success", "message": "客户端已移除"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)
