#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
应急消防巡查自动化脚本
========================
功能：自动填写「九小场所专项巡查」表单。
      支持多问题（1/6/9）选「是」→ 自行处置 → 上传图片 → 分类 → 提交。
      其余问题自动填「否」，最后可自动提交表单。

用法：
  python autofill_problem1.py          # 默认只报告问题1
  python autofill_problem1.py 6        # 只报告问题6
  python autofill_problem1.py 1,6,9    # 报告问题1、6、9

换设备注意事项：见文件顶部「换设备移植配置」区域。
"""

import subprocess
import time
import re
import sys
import os
import random
import xml.etree.ElementTree as ET
from datetime import datetime


# ============================================================
# 换设备移植配置 — 换设备后优先调整这里！
# ============================================================
# 原理：脚本用 find_clickable_by_text() 做大部分元素定位（自适应），
#       但以下场景 UIAutomator 无法识别元素内容，不得不依赖相对坐标：
#         a) 图库中选图片 — 图片网格不暴露给 UIAutomator
#         b) 时间选择器滚轮 — 滚轮值不暴露精确位置
#         c) 表单滑动 — WebView 中滑动距离和位置关系
#       换设备后这些比例值可能需要微调。
# ============================================================

ADB_PATH = "./adb.exe"                 # adb 路径（Windows 用 .exe）
TEMP_XML = "./ui_latest.xml"           # 临时 UI dump 文件名
SCREENSHOT_DIR = "./screenshots"       # 截图保存目录
MAX_WAIT_SECONDS = 10                  # 等待元素出现的最大秒数
MAX_RETRIES = 3                        # 点击操作最大重试次数
DEBUG = True                           # 是否打印 ADB 命令

# --- 图库选图坐标（相对屏幕比例）---
# UIAutomator 看不到图库中的单张图片，只能盲点「最近照片」横条。
# 基准设备 1264×2780，换设备后如果点不到图，调整比例。
IMAGE_1_RX = 0.71    # 整改前图片的 x 比例 (900/1264)
IMAGE_1_RY = 0.136   # 整改前图片的 y 比例 (379/2780)
IMAGE_2_RX = 0.46    # 整改后图片的 x 比例 (582/1264)
IMAGE_2_RY = 0.142   # 整改后图片的 y 比例 (394/2780)

# --- 时间选择器滚轮 ---
# 分钟列位于屏幕右侧 x≈0.77，滑动起点 y≈0.885。
# 基准: dy_rel=-0.777 对应约 20 分钟，每 ±0.039 ≈ ±1 分钟。
# 换设备后如果时间不准，调整 BASE_DY_REL 和 PER_MINUTE_REL。
TIME_PICKER_RX = 0.77          # 分钟列的 x 中心比例
TIME_PICKER_RY_START = 0.885   # 滑动起点 y 比例
TIME_PICKER_BASE_DY_REL = -0.777   # 20 分钟的基准滑动距离（屏高比）
TIME_PICKER_PER_MINUTE_REL = 0.039 # 每分钟对应滑动距离（屏高比）

# --- 表单内滑动参数 ---
# WebView 中滑动巡查表单/隐患详情页时使用。
# 水平位置 x=0.27 对应屏幕左 27%，避开了 AI 悬浮按钮。
# 垂直范围 80%↔20% 保证滑动被识别，范围 63%↔5% 用于大幅翻页。
SCROLL_X = 0.27             # 滑动操作的 x 位置
SCROLL_DOWN_START = 0.80    # 向下翻页起点 y
SCROLL_DOWN_END = 0.20      # 向下翻页终点 y
SCROLL_BIG_START = 0.63     # 大幅翻页起点 y（隐患详情页用）
SCROLL_BIG_END = 0.05       # 大幅翻页终点 y

# --- 字段点击偏移 ---
# 表单字段的「请选择」/下拉箭头通常在字段右侧。
# 这个比例表示：字段 y 坐标不变，x = screen_w * 0.92 作为点击位置。
FIELD_RIGHT_CLICK_RX = 0.92

# ============================================================
# 业务配置 — 通常不需要改
# ============================================================

# 是否最终提交表单（测试时 False，生产时 True）
AUTO_SUBMIT = False

# 是否跳过导航到企业列表（设备已在列表页时 True）
SKIP_NAVIGATION = True

# 所有支持的问题配置（num = 巡查项编号，keyword = 问题文本唯一关键词）
ALL_PROBLEM_CONFIG = {
    1:  {"keyword": "出口、通道",   "category": "消防安全", "subcategory": "出口、通道不畅通"},
    6:  {"keyword": "电动自行车",   "category": "消防安全", "subcategory": "电动车室内停放、充电"},
    9:  {"keyword": "灭火器",       "category": "消防安全", "subcategory": "消防设施检查"},
}

# 导航步骤（仅 SKIP_NAVIGATION=False 时使用）
# 实测：「工作台」不存在，导航基本依赖 SKIP_NAVIGATION=True
NAV_STEPS = [
    ("工作台", 2000, "首页工作台"),
    ("掌上基层", 3000, "掌上基层入口"),
    ("应急消防", 3000, "应急消防模块"),
    ("专项巡查任务", 1000, "专项巡查任务列表"),
    ("应急专项巡查", 1000, "应急专项巡查"),
    ("九小场所专项巡查任务", 1000, "九小场所任务"),
]


def get_problems_to_report():
    """根据命令行参数解析要报告的问题列表"""
    if len(sys.argv) > 1:
        nums = []
        for part in sys.argv[1].split(","):
            n = int(part.strip())
            if n in ALL_PROBLEM_CONFIG:
                nums.append(n)
            else:
                print(f"[警告] 问题 #{n} 无配置，已跳过")
        if nums:
            return [{"num": n, **ALL_PROBLEM_CONFIG[n]} for n in nums]
    return [{"num": 1, **ALL_PROBLEM_CONFIG[1]}]


PROBLEMS_TO_REPORT = get_problems_to_report()


# ============================================================
# 底层工具函数
# ============================================================

def run_adb(*args, check=True):
    """运行 ADB 命令"""
    cmd = [ADB_PATH] + [str(a) for a in args]
    if DEBUG:
        short = ' '.join(cmd[:5])
        if len(cmd) > 5:
            short += '...'
        print(f"  [ADB] {short}")
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def screenshot(name=None):
    """截屏存到 SCREENSHOT_DIR"""
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    if name is None:
        name = datetime.now().strftime("%H%M%S")
    fname = f"{SCREENSHOT_DIR}/{name}.png"
    run_adb("shell", "screencap", "-p", "/sdcard/sc_tmp.png", check=False)
    run_adb("pull", "/sdcard/sc_tmp.png", fname, check=False)
    run_adb("shell", "rm", "/sdcard/sc_tmp.png", check=False)
    if os.path.exists(fname):
        print(f"  [截图] {fname}")
    return fname


def get_latest_ui(retries=3):
    """
    dump + pull 设备 UI XML，返回 (root, screen_w, screen_h)。
    屏幕尺寸从 root node 的 bounds 自动获取，适配不同设备。
    """
    for _ in range(retries):
        r = run_adb("shell", "uiautomator", "dump", "--compressed",
                     f"/sdcard/{TEMP_XML}", check=False)
        if r.returncode != 0:
            time.sleep(0.5)
            continue

        r = run_adb("pull", f"/sdcard/{TEMP_XML}", check=False)
        if os.path.exists(TEMP_XML):
            try:
                with open(TEMP_XML, "r", encoding="utf-8") as f:
                    xml_str = f.read()
                root = ET.fromstring(xml_str)
                # 从 root bounds 自动获取屏幕尺寸（自适应不同分辨率）
                root_bounds = root.attrib.get("bounds", "[0,0][1264,2780]")
                m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', root_bounds)
                if m:
                    screen_w = int(m.group(3))
                    screen_h = int(m.group(4))
                else:
                    screen_w, screen_h = 1264, 2780
                return root, screen_w, screen_h
            except Exception as e:
                if DEBUG:
                    print(f"  [DEBUG] XML 解析失败: {e}")
                time.sleep(0.5)
                continue
            finally:
                if os.path.exists(TEMP_XML):
                    os.remove(TEMP_XML)
                run_adb("shell", "rm", f"/sdcard/{TEMP_XML}", check=False)
        time.sleep(0.5)

    print("[错误] 无法获取 UI 结构")
    return None, None, None


def get_screen_size():
    """仅获取屏幕尺寸"""
    _, sw, sh = get_latest_ui()
    return sw or 1264, sh or 2780


def parse_bounds(bounds_str):
    r"""解析 [x1,y1][x2,y2] → (cx, cy) 中心坐标"""
    m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds_str)
    if m:
        x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        return (x1 + x2) / 2, (y1 + y2) / 2
    return None


def _is_visible(bounds_str):
    """WebView 中不可见元素的 bounds 为 [0,0][0,0]"""
    return bounds_str and bounds_str != "[0,0][0,0]"


def _text_matches(node, keyword):
    """子串匹配"""
    return keyword in node.attrib.get("text", "")


def _iter_all_nodes(root):
    """遍历 XML 树中的所有节点"""
    yield root
    for child in root:
        yield from _iter_all_nodes(child)


# ============================================================
# 元素查找函数（纯文本匹配，自适应不同设备）
# ============================================================

def find_nodes_by_text(root, keyword, visible_only=True):
    """遍历查找包含 keyword 的节点（替代 XPath，支持中文）"""
    results = []
    for node in _iter_all_nodes(root):
        if _text_matches(node, keyword):
            if not visible_only or _is_visible(node.attrib.get("bounds", "")):
                results.append(node)
    return results


def find_clickable_by_text(root, keyword, visible_only=True):
    """
    查找包含指定文本的「可点击」元素。
    WebView 中文本通常在 TextView（不可点击）内，
    而其父 View 才是 clickable=true，此函数会向上追溯到可点击父节点。
    返回 (clickable_node, text, cx, cy) 或 None
    """
    matches = find_nodes_by_text(root, keyword, visible_only)

    # 优先：自身可点击
    for node in matches:
        text = node.attrib.get("text", "")
        if node.attrib.get("clickable") == "true":
            center = parse_bounds(node.attrib.get("bounds", ""))
            if center:
                return node, text, center[0], center[1]

    # 自身不可点击 → 向上找可点击的父节点
    for node in matches:
        text = node.attrib.get("text", "")
        parent = _find_clickable_ancestor(root, node)
        if parent is not None:
            center = parse_bounds(parent.attrib.get("bounds", ""))
            if center:
                return parent, text, center[0], center[1]

    return None


def _find_clickable_ancestor(root, target_node):
    """在 XML 树中向上查找 target_node 的最近可点击祖先"""
    target_bounds = target_node.attrib.get("bounds", "")

    # 收集从 root 到 target 路径上的所有祖先
    def find_path(current_root, target_bounds_str, ancestors):
        if current_root.attrib.get("bounds") == target_bounds_str:
            return list(ancestors)
        for child in current_root:
            ancestors.append(current_root)
            result = find_path(child, target_bounds_str, ancestors)
            if result is not None:
                return result
            ancestors.pop()
        return None

    ancestors = find_path(root, target_bounds, [])
    if not ancestors:
        return None

    # 从最近的祖先（列表末尾）开始找 clickable=true
    for ancestor in reversed(ancestors):
        if ancestor.attrib.get("clickable") == "true" and \
           _is_visible(ancestor.attrib.get("bounds", "")):
            return ancestor

    return None


def page_contains(keyword, timeout=MAX_WAIT_SECONDS):
    """等待页面出现包含 keyword 的可见文本（用于验证页面加载）"""
    end = time.time() + timeout
    while time.time() < end:
        root, _, _ = get_latest_ui()
        if root is None:
            time.sleep(0.5)
            continue
        nodes = find_nodes_by_text(root, keyword, visible_only=True)
        if len(nodes) > 0:
            return True
        time.sleep(0.5)
    return False


def wait_for_element(keyword, timeout_seconds=MAX_WAIT_SECONDS, clickable_only=True):
    """等待元素出现并返回坐标"""
    end_time = time.time() + timeout_seconds
    while time.time() < end_time:
        root, _, _ = get_latest_ui()
        if root is None:
            time.sleep(0.5)
            continue

        if clickable_only:
            result = find_clickable_by_text(root, keyword)
            if result:
                _, text, cx, cy = result
                print(f"  [匹配] 找到可点击元素 '{text}' @ ({cx:.0f}, {cy:.0f})")
                return {"X": cx, "Y": cy, "Text": text, "Found": True}
        else:
            nodes = find_nodes_by_text(root, keyword)
            if len(nodes) > 0:
                node = nodes[0]
                center = parse_bounds(node.attrib.get("bounds", ""))
                if center:
                    text = node.attrib.get("text", "")
                    print(f"  [匹配] 找到元素 '{text}' @ ({center[0]:.0f}, {center[1]:.0f})")
                    return {"X": center[0], "Y": center[1], "Text": text, "Found": True}
        time.sleep(0.5)

    return {"Found": False}


# ============================================================
# 点击 / 滑动 / 坐标操作
# ============================================================

def click_by_text(keyword, wait_time=1000, retries=MAX_RETRIES, verify_page_keyword=None):
    """
    文本匹配点击。这是最常用的点击方式（自适应，不依赖像素坐标）。
    verify_page_keyword: 点击后验证页面是否包含该文本
    """
    for i in range(retries):
        print(f"[尝试 {i + 1}/{retries}] 点击包含: '{keyword}'")
        result = wait_for_element(keyword)
        if result["Found"]:
            print(f"  [点击] '{result['Text']}' @ ({result['X']:.0f}, {result['Y']:.0f})")
            run_adb("shell", "input", "tap", str(result["X"]), str(result["Y"]), check=False)
            time.sleep(wait_time / 1000)

            if verify_page_keyword:
                if page_contains(verify_page_keyword, timeout=3):
                    print(f"  [验证] 页面已跳转，确认包含 '{verify_page_keyword}'")
                else:
                    print(f"  [警告] 点击后未检测到 '{verify_page_keyword}'，继续...")
            return True
        print(f"  [重试] 未找到 '{keyword}'")
        time.sleep(1)

    print(f"[失败] 多次尝试后未找到 '{keyword}'")
    screenshot(f"fail_{keyword.replace('、', '_')}")
    return False


def click_by_coords(x, y, wait_time=1000):
    """绝对坐标点击（仅用于盲点场景，如时间选择器右侧箭头）"""
    print(f"[点击坐标] ({x:.0f}, {y:.0f})")
    run_adb("shell", "input", "tap", str(int(x)), str(int(y)), check=False)
    time.sleep(wait_time / 1000)


def tap_rel(rx, ry, wait_time=1000):
    """相对坐标点击 (rx, ry ∈ 0~1)"""
    _, sw, sh = get_latest_ui()
    if sw is None:
        sw, sh = 1264, 2780
    x, y = int(rx * sw), int(ry * sh)
    click_by_coords(x, y, wait_time)


def swipe(x1, y1, x2, y2, duration=500, wait_time=1000):
    """绝对像素滑动"""
    print(f"[滑动] ({x1:.0f}, {y1:.0f}) → ({x2:.0f}, {y2:.0f}) {duration}ms")
    run_adb("shell", "input", "swipe", str(int(x1)), str(int(y1)),
            str(int(x2)), str(int(y2)), str(duration), check=False)
    time.sleep(wait_time / 1000)


def swipe_rel(rx1, ry1, rx2, ry2, duration=500, wait_time=1000):
    """相对坐标滑动 — 换设备时调整 SCROLL_* 常量即可"""
    _, sw, sh = get_latest_ui()
    if sw is None:
        sw, sh = 1264, 2780
    swipe(int(rx1 * sw), int(ry1 * sh), int(rx2 * sw), int(ry2 * sh), duration, wait_time)


def click_all_matched(keyword, wait_per_click=800, timeout_seconds=MAX_WAIT_SECONDS):
    """
    批量点击当前页所有匹配 keyword 的可见元素。
    自动跳过 (0,0) 坐标（WebView 屏幕外元素）。
    注意：此函数仅处理当前可见页，不滑动。
    """
    end_time = time.time() + timeout_seconds
    has_click = False

    while time.time() < end_time:
        root, _, _ = get_latest_ui()
        if root is None:
            time.sleep(0.5)
            continue

        nodes = find_nodes_by_text(root, keyword, visible_only=True)
        if len(nodes) == 0:
            time.sleep(0.5)
            continue

        print(f"[批量] 找到 {len(nodes)} 个可见 '{keyword}'，逐个点击")
        for node in nodes:
            bounds = node.attrib.get("bounds", "")
            center = parse_bounds(bounds)
            if center is None:
                continue
            cx, cy = center
            if cx == 0 and cy == 0:
                continue

            text = node.attrib.get("text", "")
            clickable = _find_clickable_ancestor(root, node)
            if clickable is not None:
                p_center = parse_bounds(clickable.attrib.get("bounds", ""))
                if p_center and not (p_center[0] == 0 and p_center[1] == 0):
                    cx, cy = p_center

            print(f"  [批量点击] '{text}' @ ({cx:.0f}, {cy:.0f})")
            run_adb("shell", "input", "tap", str(int(cx)), str(int(cy)), check=False)
            has_click = True
            time.sleep(wait_per_click / 1000)
        break

    if not has_click:
        print(f"[批量] 超时未找到任何可见的 '{keyword}'")
    return has_click


def find_element_center(keyword, visible_only=True):
    """查找元素中心坐标（不点击），返回 (cx, cy, text) 或 None"""
    root, _, _ = get_latest_ui()
    if root is None:
        return None
    result = find_clickable_by_text(root, keyword, visible_only)
    if result:
        return result[2], result[3], result[1]
    nodes = find_nodes_by_text(root, keyword, visible_only)
    if nodes:
        center = parse_bounds(nodes[0].attrib.get("bounds", ""))
        if center:
            return center[0], center[1], nodes[0].attrib.get("text", "")
    return None


def verify_image_uploaded(section_keyword):
    """
    验证「隐患图片」或「整改后图片」区域是否已有上传的图片。
    在该区域下方 200px 内查找 Image 节点（其 text 为 UUID，长度 > 20）。
    """
    root, _, _ = get_latest_ui()
    if root is None:
        return False

    section_nodes = [n for n in root.iter("node")
                     if section_keyword in n.attrib.get("text", "")
                     and _is_visible(n.attrib.get("bounds", ""))]
    if not section_nodes:
        return False

    # 获取 section 的 y 坐标
    section_bounds = section_nodes[0].attrib.get("bounds", "")
    m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', section_bounds)
    if not m:
        return False
    sy = int(m.group(2))

    for node in root.iter("node"):
        if node.attrib.get("class", "").endswith("Image"):
            bounds = node.attrib.get("bounds", "")
            if _is_visible(bounds):
                m2 = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                if m2:
                    img_y = int(m2.group(2))
                    if 0 < img_y - sy < 200:
                        text = node.attrib.get("text", "")
                        if text and len(text) > 0:   # 图片 ID（UUID 或 数字ID，如 27778888491712712）
                            print(f"  [验证] 图片已上传: {text[:36]}...")
                            return True
    return False


# ============================================================
# 高级操作函数
# ============================================================

def _click_nearest_upload_btn(section_keyword):
    """
    在隐患详情页上，有两个「附件最大不超过10M」按钮（隐患图片 / 整改后图片）。
    此函数找到离 section_keyword 最近且在它下方的那个按钮并点击。
    """
    root, _, _ = get_latest_ui()
    if root is None:
        return False

    section_y = None
    for node in _iter_all_nodes(root):
        if section_keyword in node.attrib.get("text", "") and _is_visible(node.attrib.get("bounds", "")):
            m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.attrib.get("bounds", ""))
            if m:
                section_y = int(m.group(2))
                break

    upload_btns = []
    for node in _iter_all_nodes(root):
        if "附件最大不超过10M" in node.attrib.get("text", "") and _is_visible(node.attrib.get("bounds", "")):
            if node.attrib.get("clickable") == "true":
                center = parse_bounds(node.attrib.get("bounds", ""))
                if center:
                    upload_btns.append((center, node))

    if not upload_btns:
        return False

    if section_y is not None and len(upload_btns) > 1:
        best = None
        best_dist = float('inf')
        for center, _ in upload_btns:
            dist = center[1] - section_y
            if 0 < dist < best_dist:
                best_dist = dist
                best = center
        if best is None:
            upload_btns.sort(key=lambda x: x[0][1])
            best = upload_btns[0][0]
    else:
        best = upload_btns[0][0]

    print(f"  [上传按钮] 选中「{section_keyword}」附近的按钮 @ ({best[0]:.0f}, {best[1]:.0f})")
    run_adb("shell", "input", "tap", str(int(best[0])), str(int(best[1])), check=False)
    return True


def upload_image(section_keyword, tap_rx, tap_ry, screenshot_label="upload"):
    """
    一次完整的图片上传流程：
    ① 点击离 section_keyword 最近的「附件最大不超过10M」→
    ② 弹出对话框，选「照片和视频」→
    ③ 图库中用 tap_rx/tap_ry 盲点图片（换设备需调这俩参数）→
    ④ 选「原图」→ ⑤ 点「发送」→ ⑥ 验证 UUID 出现
    """
    print(f"\n{'─' * 40}")
    print(f"[上传] 开始上传「{section_keyword}」图片")

    if not _click_nearest_upload_btn(section_keyword):
        print(f"  [回退] 智能定位失败，使用文本匹配")
        if not click_by_text("附件最大不超过10M", wait_time=1500):
            print(f"  [回退] 文本匹配也失败，使用相对坐标")
            tap_rel(tap_rx, tap_ry, wait_time=1500)

    if not click_by_text("照片和视频", wait_time=2000):
        screenshot(f"{screenshot_label}_no_dialog")
        return False

    time.sleep(1)
    print(f"  [步骤] 选择图片 ({tap_rx*100:.0f}%, {tap_ry*100:.0f}%)")
    tap_rel(tap_rx, tap_ry, wait_time=800)  # 盲点图库中的图片

    if not click_by_text("原图", wait_time=500):
        print("  [警告] 未找到「原图」选项，可能已默认选中")

    if not click_by_text("发送", wait_time=3000):
        screenshot(f"{screenshot_label}_no_send")
        return False

    time.sleep(2)
    if verify_image_uploaded(section_keyword):
        print(f"[上传] [OK] 「{section_keyword}」上传成功")
        return True
    else:
        print(f"[上传] [!!] 「{section_keyword}」未检测到上传结果，检查截图")
        screenshot(f"{screenshot_label}_verify")
        time.sleep(2)
        if verify_image_uploaded(section_keyword):
            print(f"[上传] [OK] 二次确认成功")
            return True
        return False


def navigate_to_business_list():
    """
    自适应导航到企业列表页（「专项巡查记录」）。
    检测当前页面，只执行必要的返回操作。
    """
    print("\n" + "=" * 50)
    print("[导航] 检查当前页面状态...")

    if page_contains("专项巡查记录", timeout=2) and page_contains("待办", timeout=1):
        print("[导航] [OK] 已在企业列表页，跳过导航")
        return True

    if page_contains("巡查项", timeout=1):
        print("[导航] 当前在巡查表单页，按返回键回到列表")
        run_adb("shell", "input", "keyevent", "4", check=False)
        time.sleep(1.5)
        if page_contains("专项巡查记录", timeout=3):
            print("[导航] [OK] 已返回企业列表页")
            return True

    if page_contains("自行处置", timeout=1) or page_contains("隐患信息", timeout=1):
        print("[导航] 当前在隐患详情页，按两次返回键回到列表")
        for _ in range(2):
            run_adb("shell", "input", "keyevent", "4", check=False)
            time.sleep(1)
        if page_contains("专项巡查记录", timeout=3):
            print("[导航] [OK] 已返回企业列表页")
            return True

    print("[导航] 开始导航到企业列表...")
    for keyword, wait_ms, desc in NAV_STEPS:
        if page_contains("专项巡查记录", timeout=1) and page_contains("待办", timeout=1):
            print(f"[导航] 已到达企业列表，跳过剩余步骤")
            return True
        if not click_by_text(keyword, wait_time=wait_ms):
            print(f"[导航] 「{desc}」({keyword}) 未找到，尝试继续...")

    if page_contains("专项巡查记录", timeout=3):
        print("[导航] [OK] 到达企业列表页")
        return True

    print("[导航] [XX] 无法导航到企业列表页")
    screenshot("nav_failed")
    return False


def click_first_business():
    """
    在「待办」列表中点击第一家企业。
    ① 点击「待办」tab 确保在正确列表
    ② 优先用尺寸特征匹配（全宽、高 150~400px、y>580）
       企业列表项结构固定，比文本匹配更可靠
    ③ 尺寸匹配失败则回退到文本关键词匹配
    """
    click_by_text("待办", wait_time=1000)
    time.sleep(0.5)

    root, _, _ = get_latest_ui()
    if root is None:
        return False

    # ── 方案 A（优先）：尺寸特征匹配 ──
    # 企业列表项 = 全宽 clickable View, 高度 150~400px, 在 tab 下方
    best_y = float('inf')
    best_coords = None
    for node in root.iter("node"):
        if node.attrib.get("clickable") == "true":
            bounds = node.attrib.get("bounds", "")
            if _is_visible(bounds):
                m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                if m:
                    y1, y2 = int(m.group(2)), int(m.group(4))
                    if 150 < y2 - y1 < 400 and y1 > 580:
                        cx = (int(m.group(1)) + int(m.group(3))) // 2
                        cy = (int(m.group(2)) + int(m.group(4))) // 2
                        if cy < best_y:
                            best_y = cy
                            best_coords = (cx, cy)

    if best_coords:
        cx, cy = best_coords
        print(f"[企业] 点击第一项 @ ({cx}, {cy})")
        run_adb("shell", "input", "tap", str(cx), str(cy), check=False)
        time.sleep(2)
        if page_contains("巡查项", timeout=3) or page_contains("巡查对象", timeout=2):
            print("[企业] [OK] 进入巡查表单")
            return True

    # ── 方案 B（回退）：文本关键词匹配 ──
    print("[企业] 尺寸匹配未成功，尝试文本匹配...")
    business_keywords = ["商行", "加工厂", "店", "厂", "公司"]
    for kw in business_keywords:
        result = find_clickable_by_text(root, kw)
        if result:
            _, text, cx, cy = result
            if cy < 580:
                continue
            print(f"[企业] 点击: '{text}' @ ({cx:.0f}, {cy:.0f})")
            run_adb("shell", "input", "tap", str(int(cx)), str(int(cy)), check=False)
            time.sleep(2)
            if page_contains("巡查项", timeout=3) or page_contains("巡查对象", timeout=2):
                print("[企业] [OK] 进入巡查表单")
                return True

    screenshot("no_business")
    return False


def scroll_to_problem(keyword, max_swipes=15):
    """
    滑动巡查表单直到问题文本 AND 至少一个选项（是/否）都可见。
    双重验证防止「文本可见但选项在屏幕外」导致点错问题。
    使用 SCROLL_DOWN 范围 (80%→20%)。
    """
    for _ in range(max_swipes):
        root, _, _ = get_latest_ui()
        if root is None:
            continue

        problem_y = None
        for node in _iter_all_nodes(root):
            if keyword in node.attrib.get("text", "") and _is_visible(node.attrib.get("bounds", "")):
                m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.attrib.get("bounds", ""))
                if m:
                    problem_y = int(m.group(4))
                    break

        if problem_y is not None:
            for node in _iter_all_nodes(root):
                if node.attrib.get("text") in ("是", "否") and _is_visible(node.attrib.get("bounds", "")):
                    m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.attrib.get("bounds", ""))
                    if m:
                        opt_y = int(m.group(2))
                        if 0 < opt_y - problem_y < 500:
                            print(f"  [定位] 问题 '{keyword}' + 选项均已可见 (文本 y={problem_y}, 选项 y={opt_y})")
                            return True
            print(f"  [定位] 文本可见但选项不可见(y={problem_y}), 继续滑动...")

        swipe_rel(SCROLL_X, SCROLL_DOWN_START, SCROLL_X, SCROLL_DOWN_END, duration=500, wait_time=800)
    print(f"  [!!] 未找到问题 '{keyword}' 或其选项")
    return False


def click_problem_answer(problem_keyword, choice="是"):
    """
    点击指定问题的选项（是/否/不涉及）。
    先定位问题文本的 y 位置，再找下方最近的同名选项，
    避免多个同名「是」时点错。
    """
    root, _, _ = get_latest_ui()
    if root is None:
        return False

    problem_bottom = None
    for node in _iter_all_nodes(root):
        if problem_keyword in node.attrib.get("text", "") and _is_visible(node.attrib.get("bounds", "")):
            m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.attrib.get("bounds", ""))
            if m:
                problem_bottom = int(m.group(4))
                break

    if problem_bottom is None:
        print(f"  [!!] 问题文本 '{problem_keyword}' 不可见")
        return False

    options = []
    for node in _iter_all_nodes(root):
        if node.attrib.get("text") == choice:
            parent = _find_clickable_ancestor(root, node)
            if parent is not None:
                center = parse_bounds(parent.attrib.get("bounds", ""))
                if center and center[0] > 0 and center[1] > 0:
                    options.append((center[1], center))

    if not options:
        print(f"  [!!] 未找到可点击的 '{choice}'")
        return False

    # 选问题文本下方最近的那个选项
    best = min(options, key=lambda x: x[0] - problem_bottom if x[0] > problem_bottom else float('inf'))
    if best[0] <= problem_bottom:
        best = min(options, key=lambda x: x[0])  # 回退：选最上面的

    _, center = best
    print(f"  [点选] '{problem_keyword}' → '{choice}' @ ({center[0]:.0f}, {center[1]:.0f})")
    run_adb("shell", "input", "tap", str(int(center[0])), str(int(center[1])), check=False)
    return True


def _read_counter(root):
    """读取巡查表单底部的 n/12 计数器"""
    for node in _iter_all_nodes(root):
        t = node.attrib.get("text", "")
        m = re.match(r'(\d+)/(\d+)', t)
        if m and _is_visible(node.attrib.get("bounds", "")):
            return int(m.group(1)), int(m.group(2))
    return 0, 12


def _swipe_page_down():
    """向下翻一页（80% → 20%）"""
    swipe_rel(SCROLL_X, SCROLL_DOWN_START, SCROLL_X, SCROLL_DOWN_END, duration=500, wait_time=800)


def _swipe_page_up():
    """向上翻一页（20% → 80%）"""
    swipe_rel(SCROLL_X, SCROLL_DOWN_END, SCROLL_X, SCROLL_DOWN_START, duration=500, wait_time=800)


def fill_all_remaining_no():
    """
    逐页扫描巡查表单，对剩余问题点「否」，并输出 12 题完整状态表。

    流程：
      1. 滑到顶部（问题1可见）
      2. 从上到下逐页扫描：每页检测可见问题的状态 → 对未处置的点「否」
      3. 回扫补漏
      4. 再滑一遍收集所有可见问题的最终状态
      5. 输出 1-12 题状态表，与用户命令对比验证

    状态记录规则：
      - 看到「关联事件」→ 标记 "是(已处置)"
      - 点击了「否」     → 标记 "否"
      - 问题不可见       → 保持 "?" (滑动不到位)
    """
    total = 12
    MAX_ROUNDS = 3

    ALL_KEYWORDS = {
        1: "出口、通道", 2: "三合一", 3: "餐饮", 4: "违规用电",
        5: "电气线路", 6: "电动自行车", 7: "防盗窗", 8: "消火栓",
        9: "灭火器", 10: "电气焊", 11: "易燃易爆", 12: "其他隐患",
    }

    reported_nums = {p["num"] for p in PROBLEMS_TO_REPORT}

    # 全局状态: None=未观测, "是(已处置)", "否"
    problem_state = {num: None for num in range(1, total + 1)}

    # ================================================================
    # 检测当前页所有可见问题的状态，更新 problem_state
    # ================================================================
    def _scan_page(root):
        """扫描当前页，更新每个可见问题的状态"""
        for num, kw in ALL_KEYWORDS.items():
            if problem_state[num] is not None:
                continue  # 已确认

            # 找问题文本
            prob_node = None
            for node in _iter_all_nodes(root):
                if kw in node.attrib.get("text", "") and _is_visible(node.attrib.get("bounds", "")):
                    prob_node = node
                    break
            if prob_node is None:
                continue

            m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', prob_node.attrib.get("bounds", ""))
            if not m:
                continue
            prob_yb = int(m.group(4))

            # 检查「关联事件」
            for node in _iter_all_nodes(root):
                if "关联事件" in node.attrib.get("text", "") and _is_visible(node.attrib.get("bounds", "")):
                    m2 = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.attrib.get("bounds", ""))
                    if m2 and 0 < int(m2.group(2)) - prob_yb < 400:
                        problem_state[num] = "是(已处置)"
                        break

    # ================================================================
    # 在当前页点击「否」（跳过已处置的）
    # ================================================================
    def _click_no_on_page(root):
        """点击当前页可见的「否」（跳过关联事件旁的），返回点击数"""
        markers_y = []
        for node in _iter_all_nodes(root):
            if "关联事件" in node.attrib.get("text", "") and _is_visible(node.attrib.get("bounds", "")):
                m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.attrib.get("bounds", ""))
                if m:
                    markers_y.append(int(m.group(2)))

        clicked = 0
        for node in _iter_all_nodes(root):
            if node.attrib.get("text") == "否" and _is_visible(node.attrib.get("bounds", "")):
                parent = _find_clickable_ancestor(root, node)
                if parent is not None:
                    c = parse_bounds(parent.attrib.get("bounds", ""))
                    if c and c[0] > 0 and c[1] > 0:
                        if not any(abs(c[1] - my) < 300 for my in markers_y):
                            run_adb("shell", "input", "tap", str(int(c[0])), str(int(c[1])), check=False)
                            clicked += 1
                            time.sleep(0.6)
        return clicked

    # 点击了「否」后标记对应问题（尽力——找被点击的最下方可见问题）
    def _mark_clicked_no(root):
        """点击否后，将下方最近的可观测问题标记为「否」"""
        for num, kw in ALL_KEYWORDS.items():
            if problem_state[num] is not None:
                continue
            for node in _iter_all_nodes(root):
                if kw in node.attrib.get("text", "") and _is_visible(node.attrib.get("bounds", "")):
                    problem_state[num] = "否"
                    break

    # ================================================================
    # 一轮完整扫描
    # ================================================================
    def _one_round():
        nonlocal problem_state
        total_clicked = 0

        # Pass 1: 滑到顶部（问题1的文本可见 或 计数器不再变化）
        prev_n = -1
        for _ in range(20):
            root, _, _ = get_latest_ui()
            if root is None:
                continue
            _scan_page(root)
            # 问题1文本或选项可见 = 到顶
            kw1 = ALL_KEYWORDS[1]
            at_top = False
            for node in _iter_all_nodes(root):
                if kw1 in node.attrib.get("text", "") and _is_visible(node.attrib.get("bounds", "")):
                    at_top = True
                    break
            if at_top:
                print("    到顶", flush=True)
                break
            # 计数器不再变化也退出
            n, _ = _read_counter(root)
            if n == prev_n and prev_n > 0:
                break
            prev_n = n
            _swipe_page_up()

        # Pass 2: 从上到下
        prev_n = -1
        stuck = 0
        for _ in range(30):
            root, _, _ = get_latest_ui()
            if root is None:
                continue
            n, _ = _read_counter(root)
            _scan_page(root)
            c = _click_no_on_page(root)
            _mark_clicked_no(root)
            total_clicked += c
            confirmed = sum(1 for v in problem_state.values() if v is not None)
            print(f"    [{n}/{total}] 点{c}个 已识别{confirmed}/12", flush=True)

            if n >= total:
                return n, total_clicked
            # 到底检测：问题12的文本可见
            kw12 = ALL_KEYWORDS[12]
            at_bottom = any(kw12 in node.attrib.get("text", "") and _is_visible(node.attrib.get("bounds", ""))
                           for node in _iter_all_nodes(root))
            # 防卡死：计数器停滞 或 已到底且无进展
            if n == prev_n:
                stuck += 1
                if stuck >= 3 or (at_bottom and stuck >= 1):
                    print(f"    停滞({stuck}页){' 已到底' if at_bottom else ''}, 结束")
                    break
            else:
                stuck = 0
            prev_n = n
            _swipe_page_down()

        # Pass 3: 回扫
        prev_n = -1
        stuck = 0
        for _ in range(30):
            root, _, _ = get_latest_ui()
            if root is None:
                continue
            n, _ = _read_counter(root)
            _scan_page(root)
            c = _click_no_on_page(root)
            _mark_clicked_no(root)
            total_clicked += c
            confirmed = sum(1 for v in problem_state.values() if v is not None)
            print(f"    [{n}/{total}] 点{c}个 已识别{confirmed}/12", flush=True)

            if n >= total:
                return n, total_clicked
            kw1 = ALL_KEYWORDS[1]
            at_top = any(kw1 in node.attrib.get("text", "") and _is_visible(node.attrib.get("bounds", ""))
                        for node in _iter_all_nodes(root))
            if n == prev_n:
                stuck += 1
                if stuck >= 3 or (at_top and stuck >= 1):
                    print(f"    停滞({stuck}页){' 已到顶' if at_top else ''}, 结束")
                    break
            else:
                stuck = 0
            prev_n = n
            _swipe_page_up()

        root, _, _ = get_latest_ui()
        n, _ = _read_counter(root) if root is not None else (0, total)
        return n, total_clicked

    # ================================================================
    # 主逻辑
    # ================================================================
    print(f"\n{'─' * 40}")
    print("[批量] 逐页扫描 + 记录每题状态...")

    final_n = 0
    total_clicked = 0
    for rd in range(1, MAX_ROUNDS + 1):
        root, _, _ = get_latest_ui()
        if root is not None:
            n, _ = _read_counter(root)
            if n >= total:
                final_n = n
                break
        print(f"  第 {rd}/{MAX_ROUNDS} 轮...")
        final_n, clicked = _one_round()
        total_clicked += clicked
        if final_n >= total:
            break
        print(f"  本轮: {final_n}/{total}, 重试...")
        time.sleep(1)

    # ================================================================
    # 补充扫描：仅在未完整时补扫收集状态
    # ================================================================
    if final_n < total or any(v is None for v in problem_state.values()):
        for _ in range(10):
            _swipe_page_up()
        for _ in range(25):
            root, _, _ = get_latest_ui()
            if root is not None:
                _scan_page(root)
            _swipe_page_down()

    # ================================================================
    # 输出 12 题完整状态表
    # ================================================================
    print(f"\n{'─' * 40}")
    print(f"[结果] 12 题填写状态 (计数器 {final_n}/{total}):")
    print(f"{'─' * 40}")

    all_match = True
    for num in range(1, total + 1):
        st = problem_state.get(num)
        display = st if st else "?"
        if num in reported_nums:
            # 用户要求「是」
            ok = (st == "是(已处置)")
            flag = "[OK]" if ok else "[!!] 应为是"
            if not ok:
                all_match = False
        else:
            # 用户要求「否」
            ok = (st == "否")
            # 如果计数器满但没观测到，大概率是「否」(只是没被扫到)
            if st is None and final_n >= total:
                display = "否*"  # 推断
                ok = True
            flag = "[OK]" if ok else f"[!!] 应为否"
            if not ok:
                all_match = False
        print(f"  问题{num:>2}: {display:<10} {flag}")

    print(f"{'─' * 40}")
    if all_match and final_n >= total:
        print(f"[批量] [OK] 全部正确，与用户命令一致")
    else:
        print(f"[批量] [!!] 存在问题，请检查上方标记 [!!] 的项")
        screenshot("incomplete_scan")


def fill_hazard_details(hazard_category="消防安全", hazard_subcategory="出口、通道不畅通"):
    """
    填写隐患详情页：分类选择 → 整改用时 → 确认提交。
    hazard_category / hazard_subcategory 需匹配分类选择器中的实际文本。
    """
    print(f"\n{'─' * 40}")
    print(f"[详情] 填写隐患分类: {hazard_category} → {hazard_subcategory}")

    # 滚到底部（「事件基础信息」区域）
    swipe_rel(SCROLL_X, SCROLL_BIG_START, SCROLL_X, SCROLL_BIG_END, duration=800, wait_time=1500)

    if not page_contains("问题隐患类型", timeout=2):
        print("[详情] 「问题隐患类型」不可见，再次滑动")
        swipe_rel(SCROLL_X, SCROLL_BIG_START, SCROLL_X, SCROLL_BIG_END, duration=800, wait_time=1000)

    # 点击分类选择器右侧箭头
    result = find_element_center("问题隐患类型")
    if result:
        _, cy, _ = result
        _, sw2, _ = get_latest_ui()
        if sw2:
            click_by_coords(sw2 * FIELD_RIGHT_CLICK_RX, cy, wait_time=1500)
    else:
        click_by_text("请选择", wait_time=1500)

    # 选大类 → 子类
    if not click_by_text(hazard_category, wait_time=1500):
        screenshot("no_category")
        return False
    if not click_by_text(hazard_subcategory, wait_time=1000):
        screenshot("no_subcategory")
        return False

    time.sleep(0.5)

    if page_contains(hazard_subcategory, timeout=2):
        print(f"[详情] [OK] 隐患分类: {hazard_category} → {hazard_subcategory}")
    else:
        print("[详情] [!!] 分类选择结果未确认")

    # ── 填写隐患整改用时 ──
    print("[详情] 填写隐患整改用时...")
    for _ in range(3):
        if page_contains("隐患整改用时", timeout=1):
            break
        swipe_rel(SCROLL_X, SCROLL_DOWN_START, SCROLL_X, SCROLL_DOWN_END, duration=300, wait_time=800)

    if not page_contains("隐患整改用时", timeout=2):
        print("[详情] [!!] 未找到「隐患整改用时」字段，跳过")
        return True

    result = find_element_center("隐患整改用时")
    if result:
        _, cy, _ = result
        _, sw2, _ = get_latest_ui()
        if sw2:
            click_by_coords(sw2 * FIELD_RIGHT_CLICK_RX, cy, wait_time=1500)
    else:
        click_by_text("隐患整改用时", wait_time=1000)
        click_by_text("请选择", wait_time=500)

    # ── 时间选择器 ──
    if page_contains("时", timeout=2) and page_contains("分", timeout=1):
        target_minutes = random.randint(18, 23)
        dy_rel = TIME_PICKER_BASE_DY_REL + (20 - target_minutes) * TIME_PICKER_PER_MINUTE_REL
        ry_end = TIME_PICKER_RY_START + dy_rel
        print(f"  [时间选择器] 设置整改用时 ~{target_minutes}分")
        swipe_rel(TIME_PICKER_RX, TIME_PICKER_RY_START, TIME_PICKER_RX, ry_end, duration=1000, wait_time=1000)
        if page_contains("完成", timeout=1):
            click_by_text("完成", wait_time=1000)
            print("  [时间选择器] 已关闭")
    else:
        print("  [!!] 时间选择器未弹出")

    # ── 提交隐患项 ──
    time.sleep(1)
    if page_contains("确认", timeout=3):
        print("[详情] 点击「确认」提交隐患项...")
        click_by_text("确认", wait_time=12000)
        print("[详情] [OK] 隐患项已提交，返回巡查表单")
        return True
    else:
        print("[详情] [!!] 未找到「确认」按钮")
        screenshot("no_confirm_hazard")
        return False


def fill_one_problem(problem_keyword, hazard_category, hazard_subcategory, problem_label=""):
    """
    一道题的完整流程：定位 → 是 → 自行处置 → 图片 → 分类 → 用时 → 确认。
    """
    label = f" [{problem_label}]" if problem_label else ""
    print(f"\n{'=' * 50}")
    print(f"[问题]{label} {problem_keyword}")
    print(f"[分类] {hazard_category} → {hazard_subcategory}")

    if not scroll_to_problem(problem_keyword):
        return False
    if not click_problem_answer(problem_keyword, "是"):
        print(f"  [回退] click_problem_answer 失败，尝试 click_by_text")
        if not click_by_text("是", wait_time=1500):
            return False
    time.sleep(1)

    if not click_by_text("自行处置", wait_time=2000):
        return False
    if not page_contains("隐患信息", timeout=3) and not page_contains("自行处置", timeout=2):
        print("  [!!] 未进入隐患详情页")
        return False
    print("  [OK] 进入隐患详情页")

    upload_image("隐患图片", IMAGE_1_RX, IMAGE_1_RY, f"p{problem_label}_before")
    # 滑动让「整改后图片」区域可见（隐患详情页较短，用大幅翻页）
    swipe_rel(SCROLL_X, SCROLL_BIG_START, SCROLL_X, SCROLL_DOWN_END, duration=500, wait_time=1500)
    if not page_contains("整改后图片", timeout=2):
        swipe_rel(SCROLL_X, SCROLL_BIG_START, SCROLL_X, SCROLL_DOWN_END, duration=500, wait_time=1000)
    upload_image("整改后图片", IMAGE_2_RX, IMAGE_2_RY, f"p{problem_label}_after")

    return fill_hazard_details(hazard_category, hazard_subcategory)


# ============================================================
# 设备检查
# ============================================================

def check_device():
    """检查 ADB 和设备连接状态"""
    global ADB_PATH

    print("=" * 50)
    print("应急消防巡查自动化脚本")
    print("=" * 50)

    adb_found = False
    if os.path.exists(ADB_PATH):
        adb_found = True
    else:
        try:
            subprocess.run(["adb", "version"], capture_output=True, check=True)
            ADB_PATH = "adb"
            adb_found = True
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

    if not adb_found:
        print(f"[错误] 找不到 adb")
        print("请将 adb.exe 放在脚本同一目录或加入 PATH")
        input("按回车键退出")
        sys.exit(1)

    try:
        result = subprocess.run([ADB_PATH, "devices"], capture_output=True, text=True, check=False)
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        if len(lines) < 2 or "device" not in lines[-1]:
            print("[错误] 未检测到已连接的 Android 设备")
            print("请检查 USB 连接、开发者选项、USB 调试授权")
            input("按回车键退出")
            sys.exit(1)
        print(f"[设备] {lines[1].split()[0]}")
    except FileNotFoundError:
        print(f"[错误] 找不到 {ADB_PATH}")
        input("按回车键退出")
        sys.exit(1)

    sw, sh = get_screen_size()
    print(f"[屏幕] {sw}×{sh}")
    print()
    print("3 秒后开始执行操作...")
    print("按 Ctrl+C 可随时终止")
    time.sleep(3)


# ============================================================
# 主流程
# ============================================================

def main():
    check_device()
    print(f"\n[开始] 执行自动化操作...")
    print(f"[配置] 需报告的问题: {[p['num'] for p in PROBLEMS_TO_REPORT]}")

    # ── 阶段 1：导航 ──
    if not SKIP_NAVIGATION:
        if not navigate_to_business_list():
            print("[错误] 导航失败，终止执行")
            return
    else:
        print("[导航] 已跳过（SKIP_NAVIGATION=True），假设已在企业列表页")
        if not page_contains("专项巡查记录", timeout=2):
            print("[警告] 当前不在企业列表页，可能出错")

    # ── 阶段 2：选择企业 ──
    print(f"\n{'=' * 50}")
    print("[阶段 2] 选择企业进入巡查表单")
    if not click_first_business():
        print("[错误] 无法进入巡查表单")
        return

    # ── 阶段 3：逐题处理「是」的问题 ──
    print(f"\n{'=' * 50}")
    print(f"[阶段 3] 处理 {len(PROBLEMS_TO_REPORT)} 个需报告的问题")
    for i, p in enumerate(PROBLEMS_TO_REPORT, 1):
        print(f"\n{'#' * 40}")
        print(f"# 问题 {i}/{len(PROBLEMS_TO_REPORT)}: #{p['num']} {p['keyword']}")
        print(f"{'#' * 40}")
        ok = fill_one_problem(
            problem_keyword=p["keyword"],
            hazard_category=p["category"],
            hazard_subcategory=p["subcategory"],
            problem_label=str(p["num"]),
        )
        if ok:
            print(f"[进度] 问题 #{p['num']} [OK]")
        else:
            print(f"[进度] 问题 #{p['num']} [!!] 失败，尝试继续...")
            screenshot(f"fail_problem_{p['num']}")

    # ── 阶段 4：双向扫描填写剩余「否」 ──
    print(f"\n{'=' * 50}")
    print("[阶段 4] 逐页扫描填写剩余「否」")

    if not page_contains("巡查项", timeout=2):
        print("[批量] 等待返回巡查表单...")
        time.sleep(3)

    if page_contains("巡查项", timeout=1) or page_contains("提交表单", timeout=1):
        print("[批量] [OK] 在巡查表单，开始扫描")
        fill_all_remaining_no()
    else:
        print("[批量] [!!] 未在巡查表单，跳过")

    # ── 阶段 5：提交表单（AUTO_SUBMIT 控制） ──
    print(f"\n{'=' * 50}")
    if AUTO_SUBMIT:
        print("[阶段 5] 提交表单")
        if page_contains("提交表单", timeout=2):
            click_by_text("提交表单", wait_time=3000)
            print("[提交] 表单已提交，等待确认弹窗...")
            time.sleep(1)
            if page_contains("确认", timeout=5):
                click_by_text("确认", wait_time=5000)
                print("[提交] [OK] 最终确认完成")
            else:
                print("[提交] [!!] 未找到确认弹窗")
                screenshot("no_final_confirm")
        else:
            print("[提交] [!!] 未找到「提交表单」按钮")
            screenshot("no_submit")
    else:
        print("[阶段 5] 提交表单 (已跳过 — AUTO_SUBMIT=False)")
        print("[提示] 表单已填写完毕，请手动检查后提交")

    # ── 完成 ──
    print()
    print("=" * 50)
    print("[完成] 自动化操作执行完毕！")
    print("=" * 50)
    screenshot("done")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[中断] 用户终止脚本")
        sys.exit(0)
    except Exception as e:
        print(f"\n[异常] {e}")
        import traceback
        traceback.print_exc()
        screenshot("crash")
        sys.exit(1)
