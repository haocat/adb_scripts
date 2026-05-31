#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
应急消防巡查自动化脚本 - 智能版
===================================
改进:
  1. 动态获取屏幕尺寸，用相对坐标替代硬编码像素
  2. 页面状态检测 — 每步操作后验证页面是否跳转
  3. 智能元素查找 — 处理 WebView 嵌套 clickable 问题
  4. 图片上传 UUID 验证 — 确认图片真的上传成功
  5. 失败自动截图 — 便于排查问题
  6. 可配置图片选择坐标 — 适配不同设备
  7. 导航自动跳过已完成步骤
  8. 增强的 WebView 元素查找（处理 text 在子节点、clickable 在父节点的情况）
"""

import subprocess
import time
import re
import sys
import os
import xml.etree.ElementTree as ET
from datetime import datetime


# ======================================
# 配置参数
# ======================================
ADB_PATH = "./adb.exe"
TEMP_XML = "./ui_latest.xml"
SCREENSHOT_DIR = "./screenshots"
MAX_WAIT_SECONDS = 10
MAX_RETRIES = 3
DEBUG = True

# ======================================
# 图片选择器坐标配置（相对屏幕比例）
# 因为 UIAutomator 无法识别图片网格中的单个图片，
# 所以用相对坐标定位「最近照片」横条中的图片位置。
# 注意：这是图库中选图的坐标，不是表单上上传按钮的坐标。
# 上传按钮的点击已改用文本匹配（「附件最大不超过10M」）。
# 如果你的设备选图不准，调整下面两个比例值。
# ======================================
# 第一张图（整改前）在「最近照片」横条中的相对位置
IMAGE_1_RX = 0.71   # x / screen_w  (900/1264 ≈ 0.71)
IMAGE_1_RY = 0.136  # y / screen_h  (379/2780 ≈ 0.136)
# 第二张图（整改后）在「最近照片」横条中的相对位置
IMAGE_2_RX = 0.46   # x / screen_w  (582/1264 ≈ 0.46)
IMAGE_2_RY = 0.142  # y / screen_h  (394/2780 ≈ 0.142)

# ======================================
# 导航关键词配置
# 实测发现「工作台」不存在，「掌上基层」是首页标题不可点击，
# 真正的入口是「应急消防应用(新)」（contains 匹配用"应急消防"即可）。
# SKIP_NAVIGATION=True 时跳过所有导航步骤（设备已在企业列表页时使用）
# ======================================
SKIP_NAVIGATION = True
NAV_STEPS = [
    # (keyword, wait_ms, description)
    # 注意：第一个「工作台」实际不存在，保留为占位。如不需要请设 SKIP_NAVIGATION=True
    ("工作台", 2000, "首页工作台"),
    ("掌上基层", 3000, "掌上基层入口"),
    ("应急消防", 3000, "应急消防模块"),
    ("专项巡查任务", 1000, "专项巡查任务列表"),
    ("应急专项巡查", 1000, "应急专项巡查"),
    ("九小场所专项巡查任务", 1000, "九小场所任务"),
]


# ======================================
# 核心函数
# ======================================
def run_adb(*args, check=True):
    """运行 ADB 命令，返回 CompletedProcess"""
    cmd = [ADB_PATH] + [str(a) for a in args]
    if DEBUG:
        short = ' '.join(cmd[:5])
        if len(cmd) > 5:
            short += '...'
        print(f"  [ADB] {short}")
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def screenshot(name=None):
    """截屏保存到 SCREENSHOT_DIR"""
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
    """获取最新 UI XML，返回 (root, screen_w, screen_h) 或 (None, None, None)"""
    for _ in range(retries):
        r = run_adb("shell", "uiautomator", "dump", "--compressed", f"/sdcard/{TEMP_XML}", check=False)
        if r.returncode != 0:
            time.sleep(0.5)
            continue

        r = run_adb("pull", f"/sdcard/{TEMP_XML}", check=False)
        if os.path.exists(TEMP_XML):
            try:
                with open(TEMP_XML, "r", encoding="utf-8") as f:
                    xml_str = f.read()
                root = ET.fromstring(xml_str)
                # 从 root node 的 bounds 获取屏幕尺寸
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
    r"""解析 '\[x1,y1\][x2,y2]' → (cx, cy) 中心坐标"""
    m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds_str)
    if m:
        x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        return (x1 + x2) / 2, (y1 + y2) / 2
    return None


def _is_visible(bounds_str):
    """检查元素是否在可视区域内（bounds 不为 [0,0][0,0]）"""
    return bounds_str and bounds_str != "[0,0][0,0]"


def _text_matches(node, keyword):
    """检查节点的 text 属性是否包含 keyword（简单子串匹配）"""
    return keyword in node.attrib.get("text", "")


def _iter_all_nodes(root):
    """遍历所有节点（含 root 自身）"""
    yield root
    for child in root:
        yield from _iter_all_nodes(child)


def find_nodes_by_text(root, keyword, visible_only=True):
    """在 XML 树中查找包含指定文本的节点（遍历实现，避免 XPath 中文问题）"""
    results = []
    for node in _iter_all_nodes(root):
        if _text_matches(node, keyword):
            if not visible_only or _is_visible(node.attrib.get("bounds", "")):
                results.append(node)
    return results


def find_clickable_by_text(root, keyword, visible_only=True):
    """
    查找包含指定文本的可点击元素。
    WebView 中常见情况：文本在 TextView 上（clickable=false），
    但其父节点 View 才是 clickable=true。此函数会向上查找。
    返回 (clickable_node, text_content, cx, cy) 或 None
    """
    matches = find_nodes_by_text(root, keyword, visible_only)

    for node in matches:
        text = node.attrib.get("text", "")
        # 检查自身是否可点击
        if node.attrib.get("clickable") == "true":
            center = parse_bounds(node.attrib.get("bounds", ""))
            if center:
                return node, text, center[0], center[1]

    # 自身不可点击，向上查找可点击的父节点
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
    path = []
    def find_path(current_root, target_bounds_str, ancestors):
        if current_root.attrib.get("bounds") == target_bounds_str:
            return list(ancestors)  # 返回祖先列表（不含自身）
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

    # 从最近的祖先开始找 clickable=true 的节点
    for ancestor in reversed(ancestors):
        if ancestor.attrib.get("clickable") == "true" and \
           _is_visible(ancestor.attrib.get("bounds", "")):
            return ancestor

    return None


def page_contains(keyword, timeout=MAX_WAIT_SECONDS):
    """等待页面包含指定文本（验证页面加载）"""
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
    """
    等待并返回匹配关键词的元素坐标。
    clickable_only=True: 仅匹配可点击元素（推荐用于点击操作）
    """
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


def click_by_text(keyword, wait_time=1000, retries=MAX_RETRIES, verify_page_keyword=None):
    """
    通过文本匹配点击元素。
    - verify_page_keyword: 点击后验证页面是否包含此文本（用于确认跳转成功）
    返回 True/False
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
    """通过坐标点击（优先使用相对坐标的 tap_rel 函数）"""
    print(f"[点击坐标] ({x:.0f}, {y:.0f})")
    run_adb("shell", "input", "tap", str(int(x)), str(int(y)), check=False)
    time.sleep(wait_time / 1000)


def tap_rel(rx, ry, wait_time=1000):
    """通过相对坐标点击 (rx, ry 是 0~1 的比例)"""
    _, sw, sh = get_latest_ui()
    if sw is None:
        sw, sh = 1264, 2780
    x, y = int(rx * sw), int(ry * sh)
    click_by_coords(x, y, wait_time)


def swipe(x1, y1, x2, y2, duration=500, wait_time=1000):
    """滑动操作（绝对像素）"""
    print(f"[滑动] ({x1:.0f}, {y1:.0f}) → ({x2:.0f}, {y2:.0f}) {duration}ms")
    run_adb("shell", "input", "swipe", str(int(x1)), str(int(y1)),
            str(int(x2)), str(int(y2)), str(duration), check=False)
    time.sleep(wait_time / 1000)


def swipe_rel(rx1, ry1, rx2, ry2, duration=500, wait_time=1000):
    """通过相对坐标滑动"""
    _, sw, sh = get_latest_ui()
    if sw is None:
        sw, sh = 1264, 2780
    swipe(int(rx1 * sw), int(ry1 * sh), int(rx2 * sw), int(ry2 * sh), duration, wait_time)


def click_all_matched(keyword, wait_per_click=800, timeout_seconds=MAX_WAIT_SECONDS):
    """批量点击当前页面所有匹配关键词的可见元素（跳过 (0,0) 坐标）"""
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
                continue  # 跳过无效坐标

            text = node.attrib.get("text", "")
            # 尝试找可点击的父节点
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
    """查找元素中心坐标，不点击。返回 (cx, cy, text) 或 None"""
    root, _, _ = get_latest_ui()
    if root is None:
        return None
    result = find_clickable_by_text(root, keyword, visible_only)
    if result:
        return result[2], result[3], result[1]
    # 回退：查找任意包含文本的元素
    nodes = find_nodes_by_text(root, keyword, visible_only)
    if nodes:
        center = parse_bounds(nodes[0].attrib.get("bounds", ""))
        if center:
            return center[0], center[1], nodes[0].attrib.get("text", "")
    return None


def verify_image_uploaded(section_keyword):
    """
    验证指定区域（如 '隐患图片' 或 '整改后图片'）是否已有上传的图片。
    通过检查该区域附近是否有 Image 节点（含 UUID 的 text）。
    """
    root, _, _ = get_latest_ui()
    if root is None:
        return False

    # 找 section 节点
    section_nodes = [n for n in root.iter("node")
                     if section_keyword in n.attrib.get("text", "")
                     and _is_visible(n.attrib.get("bounds", ""))]
    if not section_nodes:
        return False

    section_y = int(section_nodes[0].attrib.get("bounds", "").split("][")[0].split(",")[1])

    # 在 section 下方找 Image 节点
    for node in root.iter("node"):
        if node.attrib.get("class", "").endswith("Image"):
            bounds = node.attrib.get("bounds", "")
            if _is_visible(bounds):
                img_y = int(bounds.split("][")[0].split(",")[1])
                # Image 应该在 section 下方 200px 以内
                if 0 < img_y - section_y < 200:
                    text = node.attrib.get("text", "")
                    if text and len(text) > 20:  # UUID 样式
                        print(f"  [验证] 图片已上传: {text[:36]}...")
                        return True
    return False


# ======================================
# 高级操作
# ======================================
def _click_nearest_upload_btn(section_keyword):
    """
    找到离 section_keyword 最近的「附件最大不超过10M」按钮并点击。
    （页面上有两个上传按钮：隐患图片 和 整改后图片，需要点对）
    """
    root, _, _ = get_latest_ui()
    if root is None:
        return False

    # 找到 section 节点的 y 坐标
    section_y = None
    for node in _iter_all_nodes(root):
        if section_keyword in node.attrib.get("text", "") and _is_visible(node.attrib.get("bounds", "")):
            bounds = node.attrib.get("bounds", "")
            m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
            if m:
                section_y = int(m.group(2))
                break

    # 找到所有「附件最大不超过10M」可点击节点
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
        # 选择 y 坐标在 section 下方且最近的那个
        best = None
        best_dist = float('inf')
        for center, node in upload_btns:
            dist = center[1] - section_y
            if 0 < dist < best_dist:  # 必须在 section 下方
                best_dist = dist
                best = center
        if best is None:
            # 没有在 section 下方的，选 y 最小的
            upload_btns.sort(key=lambda x: x[0][1])
            best = upload_btns[0][0]
    else:
        best = upload_btns[0][0]

    print(f"  [上传按钮] 选中「{section_keyword}」附近的按钮 @ ({best[0]:.0f}, {best[1]:.0f})")
    run_adb("shell", "input", "tap", str(int(best[0])), str(int(best[1])), check=False)
    return True


def upload_image(section_keyword, tap_rx, tap_ry, screenshot_label="upload"):
    """
    完整的图片上传流程：
    1. 找到离 section_keyword 最近的「附件最大不超过10M」并点击
    2. 在弹出的对话框中选择「照片和视频」
    3. 在图片选择器中点击指定相对坐标的图片
    4. 选中「原图」
    5. 点击「发送」
    6. 验证图片 UUID 是否出现
    """
    print(f"\n{'─' * 40}")
    print(f"[上传] 开始上传「{section_keyword}」图片")

    # Step A: 找到离 section 最近的上传按钮并点击
    if not _click_nearest_upload_btn(section_keyword):
        # 回退：文本匹配
        print(f"  [回退] 智能定位失败，使用文本匹配")
        if not click_by_text("附件最大不超过10M", wait_time=1500):
            print(f"  [回退] 文本匹配也失败，使用相对坐标")
            tap_rel(tap_rx, tap_ry, wait_time=1500)

    # Step B: 选择「照片和视频」
    if not click_by_text("照片和视频", wait_time=2000):
        screenshot(f"{screenshot_label}_no_dialog")
        return False

    # Step C: 在图片选择器中点击图片
    time.sleep(1)
    print(f"  [步骤] 选择图片 ({tap_rx*100:.0f}%, {tap_ry*100:.0f}%)")
    tap_rel(tap_rx, tap_ry, wait_time=800)

    # Step D: 选择「原图」
    if not click_by_text("原图", wait_time=500):
        print("  [警告] 未找到「原图」选项，可能已默认选中")

    # Step E: 点击「发送」
    if not click_by_text("发送", wait_time=3000):
        screenshot(f"{screenshot_label}_no_send")
        return False

    # Step F: 等待并验证上传结果
    time.sleep(2)
    if verify_image_uploaded(section_keyword):
        print(f"[上传] [OK] 「{section_keyword}」上传成功")
        return True
    else:
        print(f"[上传] [!!] 「{section_keyword}」未检测到上传结果，检查截图")
        screenshot(f"{screenshot_label}_verify")
        # 再等一下试试
        time.sleep(2)
        if verify_image_uploaded(section_keyword):
            print(f"[上传] [OK] 二次确认成功")
            return True
        return False


def navigate_to_business_list():
    """
    自适应导航到企业列表页（「专项巡查记录」-待办）。
    检测当前页面状态，只执行必要的导航步骤。
    """
    print("\n" + "=" * 50)
    print("[导航] 检查当前页面状态...")

    # 先检查是否已在目标页面
    if page_contains("专项巡查记录", timeout=2) and page_contains("待办", timeout=1):
        print("[导航] [OK] 已在企业列表页，跳过导航")
        return True

    if page_contains("巡查项", timeout=1):
        print("[导航] [!!] 当前在巡查表单页，按返回键回到列表")
        run_adb("shell", "input", "keyevent", "4", check=False)
        time.sleep(1.5)
        if page_contains("专项巡查记录", timeout=3):
            print("[导航] [OK] 已返回企业列表页")
            return True

    if page_contains("自行处置", timeout=1) or page_contains("隐患信息", timeout=1):
        print("[导航] [!!] 当前在隐患详情页，按两次返回键回到列表")
        for _ in range(2):
            run_adb("shell", "input", "keyevent", "4", check=False)
            time.sleep(1)
        if page_contains("专项巡查记录", timeout=3):
            print("[导航] [OK] 已返回企业列表页")
            return True

    # 需要从头导航
    print("[导航] 开始导航到企业列表...")
    for keyword, wait_ms, desc in NAV_STEPS:
        if page_contains("专项巡查记录", timeout=1) and page_contains("待办", timeout=1):
            print(f"[导航] 已到达企业列表，跳过剩余步骤")
            return True
        if not click_by_text(keyword, wait_time=wait_ms):
            print(f"[导航] [!!] 「{desc}」({keyword}) 未找到，尝试继续...")
    # 导航结束后检查
    if page_contains("专项巡查记录", timeout=3):
        print("[导航] [OK] 到达企业列表页")
        return True

    print("[导航] [XX] 无法导航到企业列表页")
    screenshot("nav_failed")
    return False


def click_first_business():
    """
    点击列表中第一家企业。
    优先通过文本匹配点击企业名，失败则用第一项 bounds 计算坐标。
    """
    root, _, _ = get_latest_ui()
    if root is None:
        return False

    # 企业名特征：包含"商行"、"店"、"厂"等，且在可点击的 View 中
    # 策略：找所有可点击的 View 中第一个包含企业名特征的
    business_keywords = ["商行", "加工厂", "店", "厂", "公司"]
    for kw in business_keywords:
        result = find_clickable_by_text(root, kw)
        if result:
            _, text, cx, cy = result
            print(f"[企业] 点击: '{text}' @ ({cx:.0f}, {cy:.0f})")
            run_adb("shell", "input", "tap", str(int(cx)), str(int(cy)), check=False)
            time.sleep(2)
            # 验证是否进入了巡查项页面
            if page_contains("巡查项", timeout=3) or page_contains("巡查对象", timeout=2):
                print("[企业] [OK] 进入巡查表单")
                return True

    # 回退：用第一个可见的可点击列表项的 bounds
    print("[企业] 未匹配到企业名，尝试用第一个列表项...")
    # 找 [0,623] 附近的第一个可见大块可点击区域
    for node in root.iter("node"):
        if node.attrib.get("clickable") == "true":
            bounds = node.attrib.get("bounds", "")
            if _is_visible(bounds):
                m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                if m:
                    y1, y2 = int(m.group(2)), int(m.group(4))
                    # 列表项高度一般在 200-300，且在页面中上部
                    if 150 < y2 - y1 < 400 and y1 > 500:
                        cx = (int(m.group(1)) + int(m.group(3))) // 2
                        cy = (int(m.group(2)) + int(m.group(4))) // 2
                        print(f"[企业] 点击列表项 @ ({cx}, {cy})")
                        run_adb("shell", "input", "tap", str(cx), str(cy), check=False)
                        time.sleep(2)
                        if page_contains("巡查项", timeout=3):
                            print("[企业] [OK] 进入巡查表单")
                            return True

    screenshot("no_business")
    return False


def fill_form_first_problem():
    """填写第一个问题：选择「是」→「自行处置」"""
    print(f"\n{'─' * 40}")
    print("[表单] 填写第一个问题")

    if not click_by_text("是", wait_time=1500):
        return False

    # 点击「是」后，处置按钮动态出现在该问题下方
    if not click_by_text("自行处置", wait_time=2000):
        return False

    # 验证进入隐患详情页
    if page_contains("隐患信息", timeout=3) or page_contains("自行处置", timeout=2):
        print("[表单] [OK] 进入隐患详情页")
        return True

    print("[表单] [!!] 未能确认进入隐患详情页")
    return True  # 即使验证失败也继续


def fill_hazard_details():
    """填写隐患分类详情：问题隐患类型 → 消防安全 → 出口、通道不畅通"""
    print(f"\n{'─' * 40}")
    print("[详情] 填写隐患分类")

    # 先滚动到表单底部（「事件基础信息」区域）
    # 使用相对坐标：从屏幕中间偏下向上滑动
    swipe_rel(0.27, 0.63, 0.27, 0.05, duration=800, wait_time=1500)

    # 检查「问题隐患类型」是否可见
    if not page_contains("问题隐患类型", timeout=2):
        print("[详情] [!!] 「问题隐患类型」不可见，再次滑动")
        swipe_rel(0.27, 0.63, 0.27, 0.05, duration=800, wait_time=1000)

    # 点击「请选择」旁边的区域来打开分类选择器
    # 「问题隐患类型」行有一个可点击的下拉箭头
    result = find_element_center("问题隐患类型")
    if result:
        _, cy, _ = result
        # 「请选择」/箭头通常在右侧，点击下拉箭头
        _, sw2, _ = get_latest_ui()
        if sw2:
            click_by_coords(sw2 * 0.92, cy, wait_time=1500)
    else:
        # 回退：点击「请选择」
        click_by_text("请选择", wait_time=1500)

    # 选择分类「消防安全」
    if not click_by_text("消防安全", wait_time=1500):
        screenshot("no_fire_safety")
        return False

    # 选择子分类「出口、通道不畅通」
    if not click_by_text("出口、通道不畅通", wait_time=1000):
        screenshot("no_sub_category")
        return False

    # 关闭分类选择器（点击空白区域或等待自动关闭）
    time.sleep(0.5)

    # 验证分类是否已选中
    if page_contains("出口、通道不畅通", timeout=2):
        print("[详情] [OK] 隐患分类已填写: 消防安全 → 出口、通道不畅通")
    else:
        print("[详情] [!!] 分类选择结果未确认")

    # ─── 填写隐患整改用时 ───
    # 分类选择器关闭后，需要再往下滑找到「隐患整改用时」字段
    print("[详情] 填写隐患整改用时...")
    for _ in range(3):
        if page_contains("隐患整改用时", timeout=1):
            break
        swipe_rel(0.27, 0.75, 0.27, 0.20, duration=300, wait_time=800)

    if not page_contains("隐患整改用时", timeout=2):
        print("[详情] [!!] 未找到「隐患整改用时」字段，跳过")
        return True

    # 点击「隐患整改用时」的「请选择」打开时间选择器
    result = find_element_center("隐患整改用时")
    if result:
        _, cy, _ = result
        _, sw2, _ = get_latest_ui()
        if sw2:
            click_by_coords(sw2 * 0.92, cy, wait_time=1500)
    else:
        click_by_text("隐患整改用时", wait_time=1000)
        # 再点一次「请选择」
        click_by_text("请选择", wait_time=500)

    # 等待时间选择器弹出
    if page_contains("时", timeout=2) and page_contains("分", timeout=1):
        print("  [时间选择器] 已打开，设置整改用时 ~20分")
        # 滑动分钟列设置时间值
        # 原始坐标: (979,2460) -> (979,300) dy=-2160 ≈ 20分钟
        # 相对坐标: rx≈0.77, ry≈0.885 → 0.108
        # 分钟列 x 范围 630-1264, 中心约 947
        swipe_rel(0.77, 0.885, 0.77, 0.11, duration=1000, wait_time=1000)
        # 点击「完成」(中心 y≈1872, rx≈0.92)
        if page_contains("完成", timeout=1):
            click_by_text("完成", wait_time=1000)
            print("  [时间选择器] 已关闭")
    else:
        print("  [!!] 时间选择器未弹出")

    # ─── 提交隐患项 ───
    # 时间选择器关闭后，需要点击「确认」提交这个隐患详情
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
def check_device():
    """检查 ADB 和设备连接状态"""
    global ADB_PATH

    print("=" * 50)
    print("应急消防巡查自动化脚本 - 智能版")
    print("=" * 50)

    # 尝试在 PATH 或当前目录找到 adb
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

    # 检查设备连接
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

    # 获取屏幕信息
    sw, sh = get_screen_size()
    print(f"[屏幕] {sw}×{sh}")
    print()
    print("3 秒后开始执行操作...")
    print("按 Ctrl+C 可随时终止")
    time.sleep(3)


# ======================================
# 主流程
# ======================================
def main():
    check_device()
    print(f"\n[开始] 执行自动化操作...")

    # ─── 阶段 1：导航 ───
    if not SKIP_NAVIGATION:
        if not navigate_to_business_list():
            print("[错误] 导航失败，终止执行")
            return
    else:
        print("[导航] 已跳过（SKIP_NAVIGATION=True），假设已在企业列表页")
        if not page_contains("专项巡查记录", timeout=2):
            print("[警告] 当前不在企业列表页，可能出错")

    # ─── 阶段 2：选择第一家企业 ───
    print(f"\n{'=' * 50}")
    print("[阶段 2] 选择第一家企业进入巡查表单")
    if not click_first_business():
        print("[错误] 无法进入巡查表单")
        return

    # ─── 阶段 3：填写第一个问题 ───
    print(f"\n{'=' * 50}")
    print("[阶段 3] 填写第一个问题（是 → 自行处置）")
    if not fill_form_first_problem():
        print("[错误] 表单填写失败")
        return

    # ─── 阶段 4：上传整改前图片 ───
    print(f"\n{'=' * 50}")
    print("[阶段 4] 上传整改前图片")
    # 图片上传区域在「隐患图片」行右侧
    # 「附件最大不超过10M」可点击区域 ≈ (0.78, 0.58) 到 (0.98, 0.68)
    upload_image("隐患图片", IMAGE_1_RX, IMAGE_1_RY, "before_fix")

    # ─── 阶段 5：上传整改后图片 ───
    print(f"\n{'=' * 50}")
    print("[阶段 5] 上传整改后图片")
    # 先滑动让「整改后图片」可见
    swipe_rel(0.27, 0.63, 0.27, 0.30, duration=500, wait_time=1500)

    # 检查「整改后图片」是否可见
    if not page_contains("整改后图片", timeout=2):
        print("[警告] 「整改后图片」不可见，尝试额外滑动")
        swipe_rel(0.27, 0.63, 0.27, 0.20, duration=500, wait_time=1000)

    upload_image("整改后图片", IMAGE_2_RX, IMAGE_2_RY, "after_fix")

    # ─── 阶段 6：填写隐患分类详情 + 整改用时 + 提交 ───
    print(f"\n{'=' * 50}")
    print("[阶段 6] 填写隐患分类、整改用时、提交")
    if not fill_hazard_details():
        print("[警告] 隐患详情填写可能不完整")

    # fill_hazard_details 已包含「确认」提交，提交后自动返回巡查表单
    # ─── 阶段 7：批量填写 ───
    print(f"\n{'=' * 50}")
    print("[阶段 7] 批量填写当前页所有「否」")

    # 确认已回到巡查表单
    if not page_contains("巡查项", timeout=2):
        print("[批量] 等待返回巡查表单...")
        time.sleep(3)
        if not page_contains("巡查项", timeout=3):
            print("[批量] [!!] 未能确认回到巡查表单，跳过批量填写")

    if page_contains("巡查项", timeout=1):
        print("[批量] [OK] 已回到巡查表单")
        # 滑动 + 批量点击「否」
        for _ in range(5):
            swipe_rel(0.28, 0.52, 0.28, 0.08, duration=500, wait_time=1000)
            click_all_matched("否", wait_per_click=800)
            print()
    else:
        print("[批量] [!!] 跳过批量填写")

    # ─── 阶段 8：提交表单 ───
    print(f"\n{'=' * 50}")
    print("[阶段 8] 提交表单")
    if page_contains("提交表单", timeout=2):
        click_by_text("提交表单", wait_time=3000)
        print("[提交] 表单已提交，等待确认弹窗...")
        # 提交后出现汇总弹窗，点击「确认」最终提交
        time.sleep(1)
        if page_contains("确认", timeout=5):
            click_by_text("确认", wait_time=5000)
            print("[提交] [OK] 最终确认完成")
        else:
            print("[提交] [!!] 未找到确认弹窗的「确认」按钮")
            screenshot("no_final_confirm")
    else:
        print("[提交] [!!] 未找到「提交表单」按钮")
        screenshot("no_submit")

    # ─── 完成 ───
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
