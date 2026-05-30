# -*- encoding=utf8 -*-
__author__ = "Hao Cat"

from airtest.core.api import *
from poco.drivers.android.uiautomation import AndroidUiautomationPoco
poco = AndroidUiautomationPoco()



# poco(text="工作台").click()

touch((691,2676))#点击工作台按钮
sleep(2.0)
touch((116,2284))#点掌上基层按钮
sleep(3.0)
touch((492,2331))#点应急消防应用按钮
sleep(3.0)
touch((769,484))#点击专项巡查任务按钮
sleep(1.0)
touch((781,506))#点应急专项巡查按钮
sleep(1.0)
touch((595,734))#点应急专项巡查按钮
sleep(1.0)
touch((642,834))#点第一家
sleep(1.0)


#进入企业巡查项目界面


##选择出口通道不畅通
touch((87,573))#点出口通道不畅通的是
sleep(1.0)
touch((330,775))#点自行处置
sleep(1.0)
touch((1090,1759.3))#点隐患图片的加号
sleep(1.0)
touch((407 ,1455))#点上传文件里的照片和视频
sleep(1.0)
##这里后续可能要加一下相册的选择 目前没有，默认首张图片为整改后、第二张图片为整改前
touch((900 ,379))#点第二张图片
sleep(1.0)
touch((212 ,2710))#点原图按钮
sleep(1.0)
touch((1057 ,2669))#点发送按钮
sleep(1.0)
swipe((344,1740),(344,840))#滑动到整改后图片
sleep(1.0)
touch((1090,1759.3))#点隐患整改图片的加号
sleep(1.0)
touch((407 ,1455))#点上传文件里的照片和视频
sleep(1.0)
touch((582 ,394))#点第一张图片
sleep(1.0)
touch((212 ,2710))#点原图按钮
sleep(1.0)
touch((1057 ,2669))#点发送按钮
sleep(1.0)
swipe((344,1740),(344,60))#滑动到底部
sleep(1.0)
touch((1163,1452))#点问题隐患类型
sleep(1.0)
touch((423,1105))#点消防安全
sleep(1.0)
touch((863,625))#点出口不畅通
sleep(1.0)
touch((1163,1834))#点隐患整改用时
sleep(1.0)
swipe((979,2460),(979,300))#滑动整改时间
sleep(1.0)
touch((1147,1846))#点完成提交整改时间
sleep(1.0)
touch((672,2651))#点确认
sleep(1.0)
##----------------------以上应该是完成了出口通道不畅通的界面--

##--接下去开始选择后面的所有问题的“否”

swipe((355,1438),(355,438))#滑动到第二题
sleep(1)
touch((175,845))
sleep(1)
touch((206,1694))#第三题否
sleep(1)
touch((206,2360))#第四题否
sleep(1)




swipe((355,1838),(355,238))#滑动到第五题
sleep(1)
touch((153,1749))#第五题否
sleep(1)
touch((179,2263))#第六题否
sleep(1)

swipe((355,1838),(355,238))#滑动到第七题
sleep(1)
touch((179,1438))#第7题否
sleep(1)
touch((179,2163))#第8题否

swipe((355,2163),(355,238))#滑动到第9题
sleep(1)
touch((179,977))#第9题否
sleep(1)
touch((179,1742))#第10题否
sleep(1)


swipe((355,2163),(355,238))#滑动到第11题
sleep(1)
touch((179,1247))#第11题否
sleep(1)
touch((179,1999))#第12题否
sleep(1)







# for i in range(13):
#     swipe((296,1266),(296,396))#滑动选项
#     sleep(1)
#     touch(exists(Template(r"tpl1780143560221.png", record_pos=(-0.354, 0.509), resolution=(1264, 2780))))
#     sleep(0.8)

