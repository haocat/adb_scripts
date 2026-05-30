<#
应急消防巡查自动化脚本 - 模糊匹配+批量点击版
更新：新增批量点击同页面所有匹配元素
#>

# 配置参数
$ADB_PATH = "./adb.exe"
$TEMP_XML = "./ui_latest.xml"
$MAX_WAIT_SECONDS = 10
$MAX_RETRIES = 3
$DEBUG = $false

# ======================================
# 核心函数
# ======================================
function Get-LatestUI {
    param(
        [int]$Retries = 2
    )
    for ($i = 0; $i -lt $Retries; $i++) {
        & $ADB_PATH shell uiautomator dump --compressed /sdcard/$TEMP_XML 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Start-Sleep -Milliseconds 500
            continue
        }
        & $ADB_PATH pull /sdcard/$TEMP_XML 2>&1 | Out-Null
        if (Test-Path $TEMP_XML) {
            try {
                $xml = [xml](Get-Content $TEMP_XML -Encoding UTF8)
                return $xml
            }
            catch {
                Start-Sleep -Milliseconds 500
                continue
            }
            finally {
                if (Test-Path $TEMP_XML) { Remove-Item $TEMP_XML -Force }
                & $ADB_PATH shell rm /sdcard/$TEMP_XML 2>&1 | Out-Null
            }
        }
        Start-Sleep -Milliseconds 500
    }
    Write-Host "[错误] 无法获取最新UI结构"
    return $null
}

# 查找单个匹配元素（原有逻辑）
function Wait-ForElement {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Keyword,
        [int]$TimeoutSeconds = $MAX_WAIT_SECONDS
    )
    $escapedKeyword = $Keyword.Replace("'", "''")
    $endTime = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $endTime) {
        $xml = Get-LatestUI
        if ($xml) {
            $nodes = $xml.SelectNodes("//node[contains(@text, '$escapedKeyword')]")
            if ($nodes.Count -gt 0) {
                $node = $nodes[0]
                if ($node.bounds -match '\[(\d+),(\d+)\]\[(\d+),(\d+)\]') {
                    $x1 = [int]$matches[1]
                    $y1 = [int]$matches[2]
                    $x2 = [int]$matches[3]
                    $y2 = [int]$matches[4]
                    Write-Host "[匹配] 找到包含 '$Keyword' 的元素: '$($node.text)'"
                    return @{
                        X = ($x1 + $x2) / 2
                        Y = ($y1 + $y2) / 2
                        Text = $node.text
                        Found = $true
                    }
                }
            }
        }
        Start-Sleep -Milliseconds 500
    }
    return @{Found = $false}
}

# 单个元素点击（原有）
function Click-ByText {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Keyword,
        [int]$WaitTime = 1000,
        [int]$Retries = $MAX_RETRIES
    )
    for ($i = 0; $i -lt $Retries; $i++) {
        Write-Host "[尝试 $($i+1)/$Retries] 查找包含: '$Keyword'"
        $result = Wait-ForElement $Keyword
        if ($result.Found) {
            Write-Host "[成功] 点击: '$($result.Text)' 坐标: ($($result.X), $($result.Y))"
            & $ADB_PATH shell input tap $result.X $result.Y
            Write-Host "[等待] $WaitTime 毫秒"
            Start-Sleep -Milliseconds $WaitTime
            return $true
        }
        Write-Host "[重试] 未找到包含 '$Keyword' 的元素"
        Start-Sleep -Milliseconds 1000
    }
    Write-Host "[失败] 多次尝试后仍未找到包含 '$Keyword' 的元素"
    return $false
}

# 新增：批量点击当前页面所有匹配关键词的元素
function Click-All-Matched {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Keyword,
        [int]$WaitPerClick = 800,
        [int]$TimeoutSeconds = $MAX_WAIT_SECONDS
    )
    $escapedKeyword = $Keyword.Replace("'", "''")
    $endTime = (Get-Date).AddSeconds($TimeoutSeconds)
    $hasClick = $false

    while ((Get-Date) -lt $endTime) {
        $xml = Get-LatestUI
        if (-not $xml) {
            Start-Sleep -Milliseconds 500
            continue
        }
        $nodes = $xml.SelectNodes("//node[contains(@text, '$escapedKeyword')]")
        if ($nodes.Count -eq 0) {
            Start-Sleep -Milliseconds 500
            continue
        }

        Write-Host "[批量匹配] 共找到 $($nodes.Count) 个包含 '$Keyword' 的元素，开始逐个点击"
        foreach ($node in $nodes) {
            if ($node.bounds -match '\[(\d+),(\d+)\]\[(\d+),(\d+)\]') {
                $x1 = [int]$matches[1]
                $y1 = [int]$matches[2]
                $x2 = [int]$matches[3]
                $y2 = [int]$matches[4]
                $cx = ($x1 + $x2) / 2
                $cy = ($y1 + $y2) / 2

                Write-Host "[批量点击] '$($node.text)' 坐标: ($cx, $cy)"
                & $ADB_PATH shell input tap $cx $cy
                $hasClick = $true
                Start-Sleep -Milliseconds $WaitPerClick
            }
        }
        break
    }

    if (-not $hasClick) {
        Write-Host "[批量点击] 超时未找到任何包含 '$Keyword' 的元素"
    }
    return $hasClick
}

# 坐标点击
function Click-ByCoords {
    param(
        [Parameter(Mandatory=$true)]
        [int]$X,
        [Parameter(Mandatory=$true)]
        [int]$Y,
        [int]$WaitTime = 1000
    )
    Write-Host "[操作] 点击坐标: ($X, $Y)"
    & $ADB_PATH shell input tap $X $Y
    Write-Host "[等待] $WaitTime 毫秒"
    Start-Sleep -Milliseconds $WaitTime
}

# 滑动
function Swipe {
    param(
        [Parameter(Mandatory=$true)]
        [int]$X1,
        [Parameter(Mandatory=$true)]
        [int]$Y1,
        [Parameter(Mandatory=$true)]
        [int]$X2,
        [Parameter(Mandatory=$true)]
        [int]$Y2,
        [int]$Duration = 500,
        [int]$WaitTime = 1000
    )
    Write-Host "[操作] 滑动: ($X1, $Y1) -> ($X2, $Y2) 持续 $Duration 毫秒"
    & $ADB_PATH shell input swipe $X1 $Y1 $X2 $Y2 $Duration
    Write-Host "[等待] $WaitTime 毫秒"
    Start-Sleep -Milliseconds $WaitTime
}

# ======================================
# 初始化检查
# ======================================
Write-Host "=============================================="
Write-Host "应急消防巡查自动化脚本 - 模糊匹配+批量点击版"
Write-Host "=============================================="
Write-Host ""

if (-not (Get-Command $ADB_PATH -ErrorAction SilentlyContinue)) {
    Write-Host "[错误] 找不到 $ADB_PATH"
    Write-Host "请将adb.exe、AdbWinApi.dll、AdbWinUsbApi.dll放在脚本同一目录"
    Write-Host ""
    Read-Host "按回车键退出"
    exit 1
}

$devices = & $ADB_PATH devices
if (-not ($devices -match "device$")) {
    Write-Host "[错误] 未检测到已连接的Android设备"
    Write-Host ""
    Write-Host "请检查USB、开发者选项、USB调试授权"
    Write-Host ""
    Read-Host "按回车键退出"
    exit 1
}

Write-Host "[成功] 设备连接成功"
Write-Host ""
Write-Host "3秒后开始执行操作..."
Write-Host "按 Ctrl+C 可随时终止脚本"
Write-Host ""
Start-Sleep -Seconds 3

# ======================================
# 执行流程
# ======================================
Write-Host "[开始] 执行自动化操作..."
Write-Host ""

# 导航步骤
Click-ByText "工作台" 2000
Click-ByText "掌上基层" 3000
Click-ByText "应急消防" 3000
Click-ByText "专项巡查任务" 1000
Click-ByText "应急专项巡查" 1000
Click-ByText "九小场所专项巡查任务" 1000

# 点击第一家企业
Click-ByCoords 642 834 1000

# 填写第一个问题
Click-ByText "是" 1000
Click-ByText "自行处置" 1000

# 上传整改前图片
Click-ByCoords 1090 1759 1000
Click-ByText "照片和视频" 1000
Click-ByCoords 900 379 1000
Click-ByText "原图" 1000
Click-ByText "发送" 1000

# 上传整改后图片
Swipe 344 1740 344 840 500 1000
Click-ByCoords 1090 1759 1000
Click-ByText "照片和视频" 1000
Click-ByCoords 582 394 1000
Click-ByText "原图" 1000
Click-ByText "发送" 1000

# 填写隐患详情
Swipe 344 1740 344 60 800 1000
Click-ByCoords 1163 1452 1000
Click-ByText "消防安全" 1000
Click-ByText "出口、通道不畅通" 1000
Click-ByCoords 1163 1834 1000
Swipe 979 2460 979 300 1000 1000
Click-ByCoords 1147 1846 1000
Click-ByText "确认" 12000

Write-Host ""
Write-Host "[成功] 完成出口通道不畅通问题填写"
Write-Host "[开始] 批量填写当前页所有「否」"
Write-Host ""

# 滑动 + 批量点击当前页面所有「否」，不再重复写多条 Click-ByText
Swipe 355 1438 355 438 500 1000
Click-All-Matched "否" 800

Swipe 355 1838 355 238 500 1000
Click-All-Matched "否" 800

Swipe 355 1838 355 238 500 1000
Click-All-Matched "否" 800

Swipe 355 2163 355 238 500 1000
Click-All-Matched "否" 800

Swipe 355 2163 355 238 500 1000
Click-All-Matched "否" 800

# ======================================
# 结束
# ======================================
Write-Host ""
Write-Host "=============================================="
Write-Host "[成功] 所有操作执行完成！"
Write-Host "请手动检查并提交表单"
Write-Host "=============================================="
Write-Host ""
Read-Host "按回车键退出"
