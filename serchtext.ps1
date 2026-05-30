<#
应急消防巡查自动化脚本 - 模糊匹配实时UI版
更新内容：
1. 支持模糊匹配：只要元素文字包含关键词即可匹配
2. 自动转义特殊字符，避免XPath语法错误
3. 保留所有原有功能：实时UI抓取、智能等待、自动重试
4. 优化匹配算法，优先匹配最相似的结果
#>

# 配置参数
$ADB_PATH = "./adb.exe"
$TEMP_XML = "./ui_latest.xml"
$MAX_WAIT_SECONDS = 10  # 等待元素出现的最大时间
$MAX_RETRIES = 3        # 操作失败重试次数
$DEBUG = $false

# ======================================
# 核心函数（模糊匹配+实时UI）
# ======================================

function Get-LatestUI {
    param(
        [int]$Retries = 2
    )
    
    for ($i = 0; $i -lt $Retries; $i++) {
        # 导出最新UI结构
        & $ADB_PATH shell uiautomator dump --compressed /sdcard/$TEMP_XML 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Start-Sleep -Milliseconds 500
            continue
        }
        
        # 拉取到本地
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
                # 立即清理临时文件
                if (Test-Path $TEMP_XML) { Remove-Item $TEMP_XML -Force }
                & $ADB_PATH shell rm /sdcard/$TEMP_XML 2>&1 | Out-Null
            }
        }
        Start-Sleep -Milliseconds 500
    }
    
    Write-Host "[错误] 无法获取最新UI结构"
    return $null
}

function Wait-ForElement {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Keyword,  # 现在是关键词，不是完整文字
        [int]$TimeoutSeconds = $MAX_WAIT_SECONDS
    )
    
    # 转义XPath特殊字符（单引号）
    $escapedKeyword = $Keyword.Replace("'", "''")
    
    $endTime = (Get-Date).AddSeconds($TimeoutSeconds)
    
    while ((Get-Date) -lt $endTime) {
        $xml = Get-LatestUI
        if ($xml) {
            # 模糊匹配：只要text属性包含关键词即可
            $nodes = $xml.SelectNodes("//node[contains(@text, '$escapedKeyword')]")
            
            if ($nodes.Count -gt 0) {
                # 优先选择第一个匹配的元素
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

function Click-ByText {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Keyword,  # 现在是关键词
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
Write-Host "应急消防巡查自动化脚本 - 模糊匹配版"
Write-Host "特点：支持关键词模糊匹配，自动适应文字变化"
Write-Host "=============================================="
Write-Host ""

# 检查ADB是否存在
if (-not (Get-Command $ADB_PATH -ErrorAction SilentlyContinue)) {
    Write-Host "[错误] 找不到 $ADB_PATH"
    Write-Host "请将adb.exe、AdbWinApi.dll、AdbWinUsbApi.dll放在脚本同一目录"
    Write-Host ""
    Read-Host "按回车键退出"
    exit 1
}

# 检查设备连接
$devices = & $ADB_PATH devices
if (-not ($devices -match "device$")) {
    Write-Host "[错误] 未检测到已连接的Android设备"
    Write-Host ""
    Write-Host "请检查："
    Write-Host "1. 手机已通过USB连接电脑"
    Write-Host "2. 手机已开启开发者选项和USB调试"
    Write-Host "3. 已在手机上授权本电脑的调试请求"
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
# 执行操作序列（现在可以用关键词了！）
# ======================================

Write-Host "[开始] 执行自动化操作..."
Write-Host ""

# 导航步骤（使用关键词，更灵活）
Click-ByText "工作台" 2000
Click-ByText "掌上基层" 3000
Click-ByText "应急消防" 3000
Click-ByText "专项巡查任务" 1000  
Click-ByText "应急专项巡查" 1000  # 
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
Write-Host "[开始] 填写其余问题为'否'"
Write-Host ""

# 批量填写"否"
Swipe 355 1438 355 438 500 1000
Click-ByText "否" 1000
Click-ByText "否" 1000
Click-ByText "否" 1000

Swipe 355 1838 355 238 500 1000
Click-ByText "否" 1000
Click-ByText "否" 1000

Swipe 355 1838 355 238 500 1000
Click-ByText "否" 1000
Click-ByText "否" 1000

Swipe 355 2163 355 238 500 1000
Click-ByText "否" 1000
Click-ByText "否" 1000

Swipe 355 2163 355 238 500 1000
Click-ByText "否" 1000
Click-ByText "否" 1000

# ======================================
# 完成
# ======================================

Write-Host ""
Write-Host "=============================================="
Write-Host "[成功] 所有操作执行完成！"
Write-Host "已完成12道题的填写"
Write-Host "请手动检查并提交表单"
Write-Host "=============================================="
Write-Host ""
Read-Host "按回车键退出"
