import subprocess
import re
import os
import time

def get_device_info_auto():
    """自动通过ADB获取设备信息"""
    print("[*] 正在自动检测设备信息...")
    
    screen_width, screen_height = None, None
    touch_max_x, touch_max_y = None, None
    
    # 获取屏幕分辨率
    try:
        output = subprocess.getoutput("adb shell wm size")
        match = re.search(r'Physical size: (\d+)x(\d+)', output)
        if match:
            screen_width = int(match.group(1))
            screen_height = int(match.group(2))
            print(f"[+] 自动检测到屏幕分辨率: {screen_width}x{screen_height}")
    except Exception as e:
        print(f"[-] 自动检测屏幕分辨率失败: {e}")
    
    # 获取触摸屏最大坐标
    try:
        output = subprocess.getoutput("adb shell getevent -p")
        match_x = re.search(r'0035.*?max\s+(\d+)', output)
        match_y = re.search(r'0036.*?max\s+(\d+)', output)
        if match_x and match_y:
            touch_max_x = int(match_x.group(1))
            touch_max_y = int(match_y.group(1))
            print(f"[+] 自动检测到触摸屏最大坐标: {touch_max_x}x{touch_max_y}")
    except Exception as e:
        print(f"[-] 自动检测触摸屏参数失败: {e}")
    
    return screen_width, screen_height, touch_max_x, touch_max_y

def get_device_info_manual():
    """手动输入设备信息"""
    print("\n[*] 请手动输入设备信息:")
    
    while True:
        try:
            screen_width = int(input("屏幕宽度(像素): "))
            screen_height = int(input("屏幕高度(像素): "))
            touch_max_x = int(input("触摸屏最大X坐标: "))
            touch_max_y = int(input("触摸屏最大Y坐标: "))
            
            if screen_width > 0 and screen_height > 0 and touch_max_x > 0 and touch_max_y > 0:
                return screen_width, screen_height, touch_max_x, touch_max_y
            else:
                print("[-] 请输入大于0的整数")
        except ValueError:
            print("[-] 请输入有效的数字")

def parse_event_file(file_path="data/event_temp.txt"):
    """解析event_temp.txt文件（简化滑动版）"""
    print(f"\n[*] 正在解析事件文件: {file_path}")
    
    if not os.path.exists(file_path):
        print(f"[-] 错误：找不到文件 {file_path}")
        print("    请确保已录制事件并保存到该文件")
        return []
    
    events = []
    current_touch = None
    total_lines = 0
    matched_lines = 0
    
    # 检测文件编码
    with open(file_path, "rb") as f:
        raw_data = f.read()
    
    # 检测UTF-16 LE BOM
    if raw_data.startswith(b'\xff\xfe'):
        print("[+] 检测到UTF-16 LE编码文件（Windows记事本默认格式）")
        content = raw_data.decode('utf-16-le')
    elif raw_data.startswith(b'\xef\xbb\xbf'):
        print("[+] 检测到UTF-8 BOM编码文件")
        content = raw_data.decode('utf-8-sig')
    else:
        # 尝试其他编码
        for encoding in ["utf-8", "gbk", "latin-1"]:
            try:
                content = raw_data.decode(encoding)
                print(f"[+] 使用{encoding}编码解码成功")
                break
            except:
                continue
        else:
            print("[-] 无法解码文件内容")
            return []
    
    lines = content.splitlines()
    total_lines = len(lines)
    print(f"[*] 共读取到 {total_lines} 行数据")
    
    # 专门针对你的数据格式的正则表达式
    pattern = re.compile(r'\[\s*(\d+\.\d+)\]\s*(\/dev\/input\/event\d+):\s*([0-9a-fA-F]+)\s*([0-9a-fA-F]+)\s*([0-9a-fA-F]+)')
    
    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        if not line or "add device" in line or "name:" in line:
            continue
        
        match = pattern.match(line)
        if not match:
            continue
        
        matched_lines += 1
        timestamp = float(match.group(1).strip())
        device = match.group(2)
        ev_type = int(match.group(3), 16)
        ev_code = int(match.group(4), 16)
        ev_value = int(match.group(5), 16)
        
        # 只处理你的触摸屏设备event5
        if device != "/dev/input/event5":
            continue
        
        # 多点触摸协议B事件类型
        EV_ABS = 0x0003
        ABS_MT_TRACKING_ID = 0x0039  # 触点ID
        ABS_MT_POSITION_X = 0x0035   # X坐标
        ABS_MT_POSITION_Y = 0x0036   # Y坐标
        SYN_REPORT = 0x0000          # 同步事件
        
        # 触点按下事件（ID != -1）
        if ev_type == EV_ABS and ev_code == ABS_MT_TRACKING_ID and ev_value != 0xffffffff:
            if current_touch is not None:
                events.append(current_touch)
            current_touch = {
                'start_time': timestamp,
                'end_time': None,
                'start_x': None,
                'start_y': None,
                'end_x': None,
                'end_y': None,
                'duration': None,
                'duration_ms': None,
                'distance': None,
                'type': 'unknown'
            }
        
        # 触点抬起事件（ID == -1）
        elif ev_type == EV_ABS and ev_code == ABS_MT_TRACKING_ID and ev_value == 0xffffffff:
            if current_touch is not None:
                current_touch['end_time'] = timestamp
                current_touch['duration'] = current_touch['end_time'] - current_touch['start_time']
                current_touch['duration_ms'] = int(round(current_touch['duration'] * 1000))
                
                # 计算移动距离
                dx = current_touch['end_x'] - current_touch['start_x']
                dy = current_touch['end_y'] - current_touch['start_y']
                current_touch['distance'] = (dx**2 + dy**2)**0.5
                
                # 判断是点击还是滑动
                if current_touch['distance'] < 50 and current_touch['duration'] < 0.5:
                    current_touch['type'] = 'click'
                else:
                    current_touch['type'] = 'swipe'
                
                events.append(current_touch)
                current_touch = None
        
        # X坐标事件
        elif ev_type == EV_ABS and ev_code == ABS_MT_POSITION_X:
            if current_touch is not None:
                if current_touch['start_x'] is None:
                    current_touch['start_x'] = ev_value
                current_touch['end_x'] = ev_value
        
        # Y坐标事件
        elif ev_type == EV_ABS and ev_code == ABS_MT_POSITION_Y:
            if current_touch is not None:
                if current_touch['start_y'] is None:
                    current_touch['start_y'] = ev_value
                current_touch['end_y'] = ev_value
    
    # 处理最后一个未完成的触摸
    if current_touch is not None and current_touch['end_time'] is None:
        if current_touch['start_x'] is not None and current_touch['start_y'] is not None:
            current_touch['end_time'] = current_touch['start_time'] + 0.1
            current_touch['duration'] = 0.1
            current_touch['duration_ms'] = 100
            current_touch['distance'] = 0
            current_touch['type'] = 'click'
            events.append(current_touch)
    
    print(f"\n[*] 匹配到 {matched_lines} 行事件数据")
    print(f"[+] 共解析到 {len(events)} 个有效触摸操作")
    return events

def convert_coords(raw_x, raw_y, screen_width, screen_height, touch_max_x, touch_max_y):
    """将原始硬件坐标转换为像素坐标"""
    pixel_x = int(round(raw_x * screen_width / touch_max_x))
    pixel_y = int(round(raw_y * screen_height / touch_max_y))
    return pixel_x, pixel_y

def generate_bat_script(events, screen_width, screen_height, touch_max_x, touch_max_y, output_file="auto_click_generated.bat"):
    """生成ADB批处理脚本（简化滑动版）"""
    print(f"\n[*] 正在生成ADB脚本: {output_file}")
    
    # 计算操作之间的间隔时间
    intervals = []
    for i in range(len(events)-1):
        interval = events[i+1]['start_time'] - events[i]['end_time']
        intervals.append(round(interval, 2))
    
    with open(output_file, "w", encoding="gbk") as f:
        f.write("@echo off\n")
        f.write("chcp 65001 >nul\n")
        f.write(f"title ADB自动点击脚本 - 最终简化版\n\n")
        
        f.write(":: ======================================\n")
        f.write(":: 设备参数\n")
        f.write(":: ======================================\n")
        f.write(f'set "ADB_PATH=adb.exe"\n')
        f.write(f'set "SCREEN_WIDTH={screen_width}"\n')
        f.write(f'set "SCREEN_HEIGHT={screen_height}"\n')
        f.write(f'set "TOUCH_MAX_X={touch_max_x}"\n')
        f.write(f'set "TOUCH_MAX_Y={touch_max_y}"\n\n')
        
        f.write(":: ======================================\n")
        f.write(":: 初始化检测\n")
        f.write(":: ======================================\n")
        f.write("echo ==================================================\n")
        f.write("echo [*] ADB自动点击脚本（最终简化版）\n")
        f.write(f"echo [*] 屏幕分辨率: {screen_width}x{screen_height}\n")
        f.write(f"echo [*] 触摸屏最大坐标: {touch_max_x}x{touch_max_y}\n")
        f.write("echo ==================================================\n")
        f.write("echo.\n")
        
        f.write('if not exist "%ADB_PATH%" (\n')
        f.write('    echo [-] 错误：找不到 %ADB_PATH%\n')
        f.write('    echo    请将adb.exe、AdbWinApi.dll、AdbWinUsbApi.dll放在脚本同一目录\n')
        f.write('    pause\n')
        f.write('    exit /b 1\n')
        f.write(')\n\n')
        
        f.write('"%ADB_PATH%" devices | findstr /r /c:"device$" >nul\n')
        f.write('if %errorlevel% neq 0 (\n')
        f.write('    echo [-] 错误：未检测到已连接的Android设备\n')
        f.write('    echo    请确保手机已开启USB调试并连接到电脑\n')
        f.write('    pause\n')
        f.write('    exit /b 1\n')
        f.write(')\n\n')
        
        f.write("echo [+] 设备连接成功\n")
        f.write("echo.\n")
        
        f.write(":: ======================================\n")
        f.write(":: 倒计时开始\n")
        f.write(":: ======================================\n")
        f.write("echo [*] 3秒后开始执行操作...\n")
        f.write("echo    按 Ctrl+C 可随时终止脚本\n")
        f.write("timeout /t 3 /nobreak >nul\n\n")
        
        f.write(":: ======================================\n")
        f.write(":: 执行操作序列\n")
        f.write(":: 说明：\n")
        f.write(":: - 点击操作：使用input tap命令，不支持指定持续时间\n")
        f.write(":: - 滑动操作：使用input swipe命令，支持指定持续时间（毫秒）\n")
        f.write(":: ======================================\n")
        f.write("echo.\n")
        f.write("echo [*] 开始执行操作...\n")
        f.write("echo.\n")
        
        for i, event in enumerate(events):
            if event['type'] == 'click':
                # 点击事件
                x, y = convert_coords(event['start_x'], event['start_y'],
                                    screen_width, screen_height, touch_max_x, touch_max_y)
                
                f.write(f":: 操作{i+1}/{len(events)}: 点击 ({x}, {y})\n")
                f.write(f":: 录制持续时间: {event['duration']:.2f}秒 ({event['duration_ms']}毫秒)\n")
                f.write(f":: 注意：input tap命令不支持指定持续时间，使用系统默认值\n")
                f.write(f"echo [*] 操作{i+1}/{len(events)}: 点击 ({x}, {y})\n")
                f.write(f'"%ADB_PATH%" shell input tap {x} {y}\n')
                
            elif event['type'] == 'swipe':
                # 滑动事件 - 单条swipe命令（只取起点和终点）
                start_x, start_y = convert_coords(event['start_x'], event['start_y'],
                                                screen_width, screen_height, touch_max_x, touch_max_y)
                end_x, end_y = convert_coords(event['end_x'], event['end_y'],
                                            screen_width, screen_height, touch_max_x, touch_max_y)
                
                f.write(f":: 操作{i+1}/{len(events)}: 滑动 ({start_x}, {start_y}) -> ({end_x}, {end_y})\n")
                f.write(f":: 持续时间: {event['duration']:.2f}秒 ({event['duration_ms']}毫秒)\n")
                f.write(f":: 移动距离: {event['distance']:.0f} 设备单位\n")
                f.write(f"echo [*] 操作{i+1}/{len(events)}: 滑动 持续{event['duration']:.2f}秒 ({event['duration_ms']}毫秒)\n")
                f.write(f'"%ADB_PATH%" shell input swipe {start_x} {start_y} {end_x} {end_y} {event["duration_ms"]}\n')
            
            # 添加等待时间
            if i < len(intervals):
                interval_ms = int(round(intervals[i] * 1000))
                f.write(f"echo [*] 等待 {intervals[i]:.2f} 秒 ({interval_ms}毫秒)...\n")
                f.write(f"powershell Start-Sleep -Milliseconds {interval_ms}\n")
                f.write("\n")
        
        f.write("\n")
        f.write(":: ======================================\n")
        f.write(":: 执行完成\n")
        f.write(":: ======================================\n")
        f.write("echo.\n")
        f.write("echo ==================================================\n")
        f.write("echo [+] 所有操作执行完成！\n")
        f.write("echo ==================================================\n")
        f.write("echo.\n")
        f.write("pause\n")
    
    print(f"[+] 脚本生成成功: {output_file}")
    print(f"[+] 共包含 {len(events)} 个操作")

def main():
    print("="*60)
    print("ADB事件解析脚本 v4.2（修正滑动持续时间显示）")
    print("功能：解析getevent录制的触摸事件，生成可直接运行的ADB脚本")
    print("特点：单条swipe命令，执行流畅，精确时间控制")
    print("="*60)
    print()
    
    # 自动检测设备信息
    screen_width, screen_height, touch_max_x, touch_max_y = get_device_info_auto()
    
    # 如果自动检测失败，让用户手动输入
    if None in [screen_width, screen_height, touch_max_x, touch_max_y]:
        print("\n[-] 自动检测设备信息失败")
        choice = input("是否手动输入设备信息？(y/n): ").strip().lower()
        if choice != 'y':
            print("[-] 无法获取设备信息，程序退出")
            time.sleep(2)
            return
        
        screen_width, screen_height, touch_max_x, touch_max_y = get_device_info_manual()
    
    # 显示最终使用的参数
    print("\n" + "="*60)
    print("最终使用的参数:")
    print(f"屏幕分辨率: {screen_width}x{screen_height}")
    print(f"触摸屏最大坐标: {touch_max_x}x{touch_max_y}")
    print(f"转换比例: X={screen_width/touch_max_x:.6f}, Y={screen_height/touch_max_y:.6f}")
    print("="*60)
    
    # 解析事件文件
    events = parse_event_file()
    if not events:
        print("[-] 没有解析到任何有效事件，程序退出")
        print("\n[重要提示] 下次录制事件后，请使用以下命令保存：")
        print("    adb shell getevent -t > data/event_temp.txt")
        print("    不要用记事本打开并保存，否则会变成UTF-16编码")
        time.sleep(10)
        return
    
    # 显示详细解析结果
    print("\n" + "="*60)
    print("详细解析结果:")
    print("="*60)
    for i, event in enumerate(events):
        if event['type'] == 'click':
            x, y = convert_coords(event['start_x'], event['start_y'],
                                screen_width, screen_height, touch_max_x, touch_max_y)
            print(f"操作{i+1}: 点击 ({x}, {y}) 持续时间: {event['duration']:.2f}秒 ({event['duration_ms']}毫秒)")
        elif event['type'] == 'swipe':
            start_x, start_y = convert_coords(event['start_x'], event['start_y'],
                                            screen_width, screen_height, touch_max_x, touch_max_y)
            end_x, end_y = convert_coords(event['end_x'], event['end_y'],
                                        screen_width, screen_height, touch_max_x, touch_max_y)
            print(f"操作{i+1}: 滑动 ({start_x}, {start_y}) -> ({end_x}, {end_y})")
            print(f"        持续时间: {event['duration']:.2f}秒 ({event['duration_ms']}毫秒)")
            print(f"        移动距离: {event['distance']:.0f} 设备单位")
    
    # 生成脚本
    output_file = input("\n请输入生成的脚本文件名(默认: auto_click_generated.bat): ").strip()
    if not output_file:
        output_file = "auto_click_generated.bat"
    if not output_file.endswith(".bat"):
        output_file += ".bat"
    
    generate_bat_script(events, screen_width, screen_height, touch_max_x, touch_max_y, output_file)
    
    print("\n[+] 所有操作完成！")
    print(f"[+] 生成的脚本文件: {os.path.abspath(output_file)}")
    print("[+] 双击脚本文件即可运行")
    print()
    input("按回车键退出...")

if __name__ == "__main__":
    # 自动创建data目录
    if not os.path.exists("data"):
        os.makedirs("data")
    
    main()
