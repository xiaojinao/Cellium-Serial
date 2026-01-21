import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import serial
import threading

# --- 固件关键字映射 ---
UART_TYPES = {
    18: "设备名称", 17: "信号强度(RSSI)", 16: "蓝牙地址", 14: "生产厂家",
    13: "系统 ID", 10: "厂商识别码(VID)", 20: "产品识别码(PID)", 11: "固件版本", 
    12: "硬件版本", 22: "电池电量"
}

# --- HID 键码映射表 ---
HID_MAP = {
    0x04: 'a', 0x05: 'b', 0x06: 'c', 0x07: 'd', 0x08: 'e', 0x09: 'f', 0x0A: 'g',
    0x0B: 'h', 0x0C: 'i', 0x0D: 'j', 0x0E: 'k', 0x0F: 'l', 0x10: 'm', 0x11: 'n',
    0x12: 'o', 0x13: 'p', 0x14: 'q', 0x15: 'r', 0x16: 's', 0x17: 't', 0x18: 'u',
    0x19: 'v', 0x1A: 'w', 0x1B: 'x', 0x1C: 'y', 0x1D: 'z', 
    0x1E: '1', 0x1F: '2', 0x20: '3', 0x21: '4', 0x22: '5', 0x23: '6', 0x24: '7', 
    0x25: '8', 0x26: '9', 0x27: '0', 0x28: 'ENTER', 0x2C: ' ', 0x2D: '-', 
    0x33: ';', 0x37: '.', 0x36: ',', 0x2E: '=', 0x2F: '[', 0x30: ']', 0x31: '\\'
}

class DongleApp:
    def __init__(self, root):
        self.root = root
        self.root.title("串口协议解析")
        self.root.geometry("1100x700")
        
        self.ser = None
        self.running = False
        self.line_buffer = "" 
        
        self.setup_ui()
        
    def setup_ui(self):
        # 顶部控制栏
        top_frame = ttk.Frame(self.root)
        top_frame.pack(pady=10, fill='x', padx=10)
        
        ttk.Label(top_frame, text="串口号:").pack(side='left')
        self.port_entry = ttk.Entry(top_frame, width=10)
        self.port_entry.insert(0, "COM3")
        self.port_entry.pack(side='left', padx=5)
        
        ttk.Label(top_frame, text="波特率:").pack(side='left', padx=5)
        self.baud_combo = ttk.Combobox(top_frame, values=["9600", "38400", "115200"], width=8)
        self.baud_combo.set("38400")
        self.baud_combo.pack(side='left', padx=5)
        
        self.btn_connect = ttk.Button(top_frame, text="开启监听", command=self.toggle_connect)
        self.btn_connect.pack(side='left', padx=10)

        # 添加清空/重置按钮
        self.btn_clear = ttk.Button(top_frame, text="清空全部数据", command=self.clear_all)
        self.btn_clear.pack(side='right', padx=10)

        # 主显示区 - 使用分栏窗体
        self.main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.main_pane.pack(fill='both', expand=True, padx=10, pady=5)
        
        # --- 左侧看板 (权重 3) ---
        self.status_frame = ttk.LabelFrame(self.main_pane, text="设备详细信息")
        self.main_pane.add(self.status_frame, weight=3) 
        
        self.info_labels = {}
        for idx, name in UART_TYPES.items():
            f = ttk.Frame(self.status_frame)
            f.pack(fill='x', padx=15, pady=6)
            ttk.Label(f, text=f"{name}:", font=("微软雅黑", 10, "bold"), width=18).pack(side='left')
            lbl = ttk.Label(f, text="等待数据...", font=("Consolas", 11), foreground="#888")
            lbl.pack(side='left', fill='x', expand=True)
            self.info_labels[idx] = lbl

        # --- 右侧日志 (权重 2) ---
        log_frame = ttk.LabelFrame(self.main_pane, text="16 进制原始流日志")
        self.main_pane.add(log_frame, weight=2) 
        
        self.log_area = scrolledtext.ScrolledText(log_frame, font=("Consolas", 9), 
                                                bg="#1e1e1e", fg="#d4d4d4", state='disabled')
        self.log_area.pack(fill='both', expand=True)
        
        # 日志颜色配置
        self.log_area.tag_configure("header", foreground="#ff4500")
        self.log_area.tag_configure("index", foreground="#32cd32")
        self.log_area.tag_configure("len", foreground="#1e90ff")
        self.log_area.tag_configure("checksum", foreground="#ffd700")

    def clear_all(self):
        """清空界面和缓冲区，准备测试新设备"""
        # 1. 清空看板标签
        for idx in self.info_labels:
            self.info_labels[idx].config(text="等待数据...", foreground="#888")
        
        # 2. 清空日志区
        self.log_area.configure(state='normal')
        self.log_area.delete('1.0', tk.END)
        self.log_area.configure(state='disabled')
        
        # 3. 重置内部缓冲区
        self.line_buffer = ""
        print("[系统]: 数据已重置，等待新设备输入...")

    def log_hex(self, idx, length, data, cs):
        self.log_area.configure(state='normal')
        self.log_area.insert('end', "AF ", "header")
        self.log_area.insert('end', "| ")
        self.log_area.insert('end', f"{idx:02X} ", "index")
        self.log_area.insert('end', "| ")
        self.log_area.insert('end', f"{length:02X} ", "len")
        self.log_area.insert('end', "| ")
        
        data_hex = " ".join([f"{b:02X}" for b in data])
        self.log_area.insert('end', f"{data_hex.ljust(23)} ") 
        
        self.log_area.insert('end', "| ")
        self.log_area.insert('end', f"{cs:02X}\n", "checksum")
        
        self.log_area.see('end')
        self.log_area.configure(state='disabled')

    def toggle_connect(self):
        if not self.running:
            try:
                self.ser = serial.Serial(self.port_entry.get(), int(self.baud_combo.get()), timeout=0.1)
                self.running = True
                self.btn_connect.config(text="断开连接")
                threading.Thread(target=self.read_serial, daemon=True).start()
            except Exception as e:
                messagebox.showerror("串口错误", str(e))
        else:
            self.running = False
            if self.ser: self.ser.close()
            self.btn_connect.config(text="开启监听")

    def read_serial(self):
        while self.running:
            try:
                if self.ser.in_waiting > 0:
                    char = self.ser.read(1)
                    if char == b'\xAF':
                        head = self.ser.read(2)
                        if len(head) < 2: continue
                        idx, length = head[0], head[1]
                        payload = self.ser.read(length + 1)
                        if len(payload) < length + 1: continue
                        
                        data = payload[:-1]
                        cs_recv = payload[-1]
                        self.root.after(0, self.log_hex, idx, length, data, cs_recv)
                        
                        calc_sum = 0x5A ^ idx ^ length
                        for b in data: calc_sum ^= b
                        if calc_sum == cs_recv:
                            self.process_logic(idx, length, data)
            except:
                break

    def process_logic(self, idx, length, data):
        if idx == 0 and length == 8:
            modifier = data[0]
            keycode = data[2]
            if keycode == 0: return
            char = HID_MAP.get(keycode, "")
            if char == "ENTER":
                self.analyze_buffer()
                self.line_buffer = ""
            elif char:
                if modifier & 0x22:
                    if char == ';': char = ':'
                    else: char = char.upper()
                self.line_buffer += char

    def analyze_buffer(self):
        raw_text = self.line_buffer.lower()
        clean_text = " ".join(raw_text.split())
        
        patterns = {
            "vid:": 10, "pid:": 20, "hw ver:": 12, "fw ver:": 11,
            "name:": 18, "addr:": 16, "battery:": 22, "manufacture:": 14,
            "id:": 13, "rssi:": 17
        }
        
        for key, idx in patterns.items():
            if key in clean_text:
                value = clean_text.split(key)[-1].strip().upper()
                self.update_ui_label(idx, value)

    def update_ui_label(self, idx, value):
        def do_update():
            # 更新为蓝色突出显示新获取的数据
            self.info_labels[idx].config(text=value, foreground="#005fb8")
        self.root.after(0, do_update)

if __name__ == "__main__":
    root = tk.Tk()
    root.option_add("*Font", ("微软雅黑", 9))
    app = DongleApp(root)
    root.mainloop()