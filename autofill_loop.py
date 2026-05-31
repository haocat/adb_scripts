#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
循环调用 autofill_problem1 自动填充多家企业
用法: python autofill_loop.py [数量]
     数量默认为 3，例如 python autofill_loop.py 5
"""

import sys
import time
import autofill_problem1 as auto


def fill_one_business(index):
    """填充一家企业的完整流程（不含 check_device）"""
    print(f"\n{'#' * 50}")
    print(f"###  第 {index} 家企业  ###")
    print(f"{'#' * 50}")

    # 确保在企业列表页
    if not auto.page_contains("专项巡查记录", timeout=2):
        print("[循环] 不在企业列表页，尝试返回...")
        for _ in range(3):
            auto.run_adb("shell", "input", "keyevent", "4", check=False)
            time.sleep(1)
            if auto.page_contains("专项巡查记录", timeout=2):
                break
        if not auto.page_contains("专项巡查记录", timeout=2):
            print("[循环] [XX] 无法回到企业列表页")
            return False

    # ─── 阶段 2：选择企业 ───
    print(f"\n{'─' * 40}")
    print("[阶段 2] 选择企业进入巡查表单")
    if not auto.click_first_business():
        print("[循环] [XX] 无法进入巡查表单")
        return False

    # ─── 阶段 3：填写第一个问题 ───
    print(f"\n{'─' * 40}")
    print("[阶段 3] 是 → 自行处置")
    if not auto.fill_form_first_problem():
        print("[循环] [XX] 表单填写失败")
        return False

    # ─── 阶段 4：上传整改前图片 ───
    print(f"\n{'─' * 40}")
    print("[阶段 4] 上传整改前图片")
    auto.upload_image("隐患图片", auto.IMAGE_1_RX, auto.IMAGE_1_RY, f"biz{index}_before")

    # ─── 阶段 5：上传整改后图片 ───
    print(f"\n{'─' * 40}")
    print("[阶段 5] 上传整改后图片")
    auto.swipe_rel(0.27, 0.63, 0.27, 0.30, duration=500, wait_time=1500)
    if not auto.page_contains("整改后图片", timeout=2):
        auto.swipe_rel(0.27, 0.63, 0.27, 0.20, duration=500, wait_time=1000)
    auto.upload_image("整改后图片", auto.IMAGE_2_RX, auto.IMAGE_2_RY, f"biz{index}_after")

    # ─── 阶段 6：填写隐患分类 + 整改用时 + 提交 ───
    print(f"\n{'─' * 40}")
    print("[阶段 6] 隐患分类 + 整改用时 + 确认")
    if not auto.fill_hazard_details():
        print("[循环] [!!] 隐患详情填写可能不完整")

    # 提交后应自动返回巡查表单
    # ─── 阶段 7：批量填写 ───
    print(f"\n{'─' * 40}")
    print("[阶段 7] 批量填写「否」")
    if not auto.page_contains("巡查项", timeout=3):
        print("[批量] 等待返回巡查表单...")
        time.sleep(3)
        if not auto.page_contains("巡查项", timeout=3):
            print("[批量] [!!] 未回到巡查表单，跳过批量填写")
        else:
            print("[批量] [OK] 已回到巡查表单")

    if auto.page_contains("巡查项", timeout=1):
        for _ in range(5):
            auto.swipe_rel(0.28, 0.52, 0.28, 0.08, duration=500, wait_time=1000)
            auto.click_all_matched("否", wait_per_click=800)
            print()

    # ─── 阶段 8：提交表单 ───
    print(f"\n{'─' * 40}")
    print("[阶段 8] 提交表单 + 最终确认")
    if auto.page_contains("提交表单", timeout=2):
        auto.click_by_text("提交表单", wait_time=3000)
        print("[提交] 等待确认弹窗...")
        time.sleep(1)
        if auto.page_contains("确认", timeout=5):
            auto.click_by_text("确认", wait_time=5000)
            print("[提交] [OK] 最终确认完成")
        else:
            print("[提交] [!!] 未找到确认弹窗")
            auto.screenshot(f"biz{index}_no_final_confirm")
    else:
        print("[提交] [!!] 未找到「提交表单」按钮")
        auto.screenshot(f"biz{index}_no_submit")

    print(f"\n[循环] [OK] 第 {index} 家企业完成")
    return True


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    print(f"\n{'=' * 50}")
    print(f"  循环自动填充脚本")
    print(f"  目标: {count} 家企业")
    print(f"{'=' * 50}")

    # 初始化设备（仅一次）
    auto.check_device()

    success = 0
    for i in range(1, count + 1):
        if fill_one_business(i):
            success += 1

        # 进度
        print(f"\n[进度] {success}/{i} 成功, {i - success} 失败, 剩余 {count - i}")

        # 间隔
        if i < count:
            time.sleep(2)

    # 汇总
    print(f"\n{'=' * 50}")
    print(f"  执行完毕：共 {count} 家，成功 {success} 家")
    print(f"{'=' * 50}")
    auto.screenshot("loop_done")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[中断] 用户终止")
        sys.exit(0)
