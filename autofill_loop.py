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
    """填充一家企业：多问题 + 批量否 + 提交"""
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

    # ─── 选择企业 ───
    if not auto.click_first_business():
        print("[循环] [XX] 无法进入巡查表单")
        return False

    # ─── 逐题处理「是」的问题 ───
    problems = auto.PROBLEMS_TO_REPORT
    for i, p in enumerate(problems, 1):
        print(f"\n[问题 {i}/{len(problems)}] #{p['num']} {p['keyword']}")
        ok = auto.fill_one_problem(
            problem_keyword=p["keyword"],
            hazard_category=p["category"],
            hazard_subcategory=p["subcategory"],
            problem_label=f"b{index}_p{p['num']}",
        )
        if not ok:
            print(f"[循环] [!!] 问题 #{p['num']} 失败，继续...")

    # ─── 批量填写剩余「否」 ───
    if not auto.page_contains("巡查项", timeout=3):
        time.sleep(3)
    if auto.page_contains("巡查项", timeout=1) or auto.page_contains("提交表单", timeout=1):
        auto.fill_all_remaining_no()

    # ─── 提交表单 ───
    if auto.AUTO_SUBMIT:
        if auto.page_contains("提交表单", timeout=2):
            auto.click_by_text("提交表单", wait_time=3000)
            time.sleep(1)
            if auto.page_contains("确认", timeout=5):
                auto.click_by_text("确认", wait_time=5000)
                print("[提交] [OK] 最终确认完成")
            else:
                auto.screenshot(f"biz{index}_no_final_confirm")
        else:
            auto.screenshot(f"biz{index}_no_submit")
    else:
        print("[提交] 已跳过 (AUTO_SUBMIT=False)")

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
