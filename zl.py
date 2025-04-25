import matplotlib.pyplot as plt
import matplotlib.image as image
from matplotlib.ticker import MultipleLocator
import pandas as pd
from datetime import datetime, timedelta
from dateutil.parser import (
    parse,
)  # 识别日期字符串。使得时间可以简写成 2024-11-1 16h 而非2024-11-1 16:00:00
from numpy import sqrt, uint8, ones, dstack
import numpy as np
from PIL import Image as PILimage
from glob import glob
from random import choice

# zl = 粥历 != 粥礼

# --------------------------------------------自定义-----------------------------------------

background_list = glob(f"./粥图" + "/*")  # 图片是16:9的png格式
background_pic_dir = choice(background_list)
texture_list = glob(f"./纹理" + "/*")  # 纹理的路径，最好也是16:9。
texture_dir = choice(texture_list)
all_data_path = r"./所有活动数据.csv"
data_path = r"./活动数据.csv"  # 事件数据

num_colors = 10  # 要提取的主要颜色数量
# --------------------------------------------------------------------------------------

# 数据读取与数据整理
# df = pd.read_csv(data_path)
df = pd.read_csv(all_data_path)
df.iloc[:, 1] = [parse(ii) for ii in df.iloc[:, 1]]  # 开始日期标准化
# 特殊时间记法处理
for ii in range(len(df.iloc[:, 2])):
    if len(df.iloc[ii, 2]) <= 2:
        if df.iloc[ii, 1].hour != 4:
            # 结束时间特殊处理，使其始终4点结束
            df.iloc[ii, 2] = str(
                df.iloc[ii, 1]
                + timedelta(days=int(df.iloc[ii, 2]))
                - timedelta(hours=12)
            )
        else:
            df.iloc[ii, 2] = str(df.iloc[ii, 1] + timedelta(days=int(df.iloc[ii, 2])))

df.iloc[:, 2] = [parse(ii) for ii in df.iloc[:, 2]]  # 结束日期标准化至4点

now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
today_weekday = now.weekday()
左边界距今天 = 3
右边界距本周一 = 22

left_border = now - timedelta(days=左边界距今天)  # 绘图的左边界时间
right_border = now + timedelta(days=右边界距本周一 - today_weekday)  # 绘图的右边界时间
df = df.loc[df.iloc[:, 2] > now + timedelta(hours=4)]  # 删除过期事件
df = df.loc[df.iloc[:, 1] < right_border]  # 删除未到事件
df = df.sort_values(by=["类型", "结束时间"], ascending=False)  # 以类型和end time排序
df.to_csv(data_path, index=False)  # 覆盖保存源文件

# 背景图片主要颜色提取
color = []
pilimg = PILimage.open(background_pic_dir)
small_image = pilimg.resize((80, 80))
result = small_image.convert("P", palette=PILimage.ADAPTIVE, colors=num_colors)
result = result.convert("RGB")
main_colors = result.getcolors()
# 显示提取的主要颜色
col_extract = []
for count, col in main_colors:
    # print([col[i]/255 for i in range(3)])#RGB转RGBA，可输出RGBA色号
    col_extract.append([col[i] / 255 for i in range(3)])
    if sum(col) > 255 * 3 * 0.382:  # 筛掉暗部
        r, g, b = col
        r, g, b = (
            round(sqrt(r / 255) * 255),
            round(sqrt(g / 255) * 255),
            round(sqrt(b / 255) * 255),
        )
        result = (r << 16) + (g << 8) + b
        color.append("#" + hex(result)[2:])

# 铺设背景图片和纹理
plt.rcParams["font.sans-serif"] = ["SimHei"]  # 替换sans-serif字体
plt.rcParams["font.size"] = 16  # 字号

fig = plt.figure(figsize=(16, 9), facecolor="silver")
ax = plt.subplot(111, frameon=False)

img = image.imread(background_pic_dir)  # 读取图片
tw = image.imread(texture_dir)  # 读取纹理

# 添加 Alpha 通道并修改alpha值
def set_alpha_channel(image_data,alphavalue):
    if alphavalue <= 1.0:
        alpha_val = round(alphavalue * 255)
    else:
        alpha_val = round(alphavalue)
    alpha_val = max(0, min(alpha_val, 255))  # 确保值在 0-255 范围内
    alpha_val = np.uint8(alpha_val)
    
    # 检查输入图像的通道数是否为 3 (RGB) 或 4 (RGBA)
    if image_data.shape[2] not in (3, 4):
        raise ValueError("Input image must have 3 (RGB) or 4 (RGBA) channels.")
    # 添加或修改 Alpha 通道
    if image_data.shape[2] == 3:
        # 创建 Alpha 通道并合并
        alpha = np.full((image_data.shape[0], image_data.shape[1]), alpha_val, dtype=np.uint8)
        return np.dstack((image_data, alpha))
    else:
        # 复制图像数据以避免修改原始数组
        image_data = image_data.copy()
        image_data[:, :, 3] = alpha_val
        return image_data

img = set_alpha_channel(img,0.6)
tw = set_alpha_channel(tw,0.2)

img[:, :, :-1] = img[:, :, :-1] / 3  # 调暗

fig.figimage(img, 0, 0, zorder=-3)  # 显示背景
fig.figimage(tw, 0, 0, zorder=-2)  # 显示纹理

# 画图
rb = (right_border - left_border).days * 24 + (
    right_border - left_border
).seconds // 3600  # 右边界小时坐标

total_event_num = 0
for ii, name in enumerate(df.iloc[:, 0]):
    tmp1 = df.iloc[ii, 2] - df.iloc[ii, 1]  # 事件实际持续时间
    tmp1 = tmp1.days * 24 + tmp1.seconds // 3600  # 事件实际持续小时
    tmp2 = df.iloc[ii, 2] - left_border  # 事件结束到左边界的时间
    tmp2 = tmp2.days * 24 + tmp2.seconds // 3600  # 事件结束到左边界的小时数
    width = min(tmp1, tmp2) + 1  # 取最小的持续小时数作为bar的宽度
    left = max(
        (df.iloc[ii, 1] - left_border).days * 24
        + (df.iloc[ii, 1] - left_border).seconds // 3600,
        -1,
    )  # 要么从开始时候画，要么从左边界画

    if (
        tmp2 > 0 and left < rb and left + width >= 3 * 24
    ):  # 选出能显示出来的事件，去掉显示效果不好的过期事件
        plt.barh(
            y=ii,
            width=width,
            left=left,
            edgecolor="k",
            linewidth=1.618,
            color=color[ii % len(color)],
            alpha=0.75,
            joinstyle="bevel",
        )
        tmp3 = right_border - df.iloc[ii, 1]
        tmp3 = tmp3.days * 24 + tmp3.seconds // 3600
        tmp4 = right_border - left_border
        tmp4 = tmp4.days * 24 + tmp4.seconds // 3600
        lwth = min(width, tmp3, tmp4)  # 对于右边界遮住的区域宽度

        if lwth <= 24 * 3:  # 右边界的文本特殊处理
            namestr = name[: lwth // 8]
        else:
            namestr = name

        plt.text(
            x=left + lwth / 2,
            y=ii,
            s=namestr,
            va="center",
            ha="center",
            fontweight="bold",
        )
        total_event_num += 1

plt.title("近期活动一览（含*预测）", c="white")  # 标题

# 设置x轴刻度为日期格式
ax.minorticks_on()  # 启用副刻度线
ax.tick_params(
    axis="both", which="major", direction="in", width=1, length=5
)  # 设置主刻度线的参数
ax.tick_params(
    axis="both", which="minor", direction="in", width=1, length=2
)  # 设置副刻度线的参数
ax.xaxis.set_minor_locator(MultipleLocator(4))  # 设置副刻度线的间隔

xticks_positions = []
xticks_labels = []

weekname = ["一", "二", "三", "四", "五", "六", "日"]
current_date = left_border
tmp, tmp2 = 0, 0
while current_date <= right_border:
    iwn = "\n·\n" + "周" + weekname[current_date.weekday()]
    tmp = (current_date - left_border).seconds // 3600 + (
        current_date - left_border
    ).days * 24
    if tmp == 0:
        xticks_positions.append(tmp)
        if (
            current_date.day + 左边界距今天 + 右边界距本周一 - today_weekday
            < (now.replace(month=(now.month + 1) % 12, day=1) - timedelta(days=1)).day
        ):
            xticks_labels.append(current_date.strftime(f"%m月{iwn}"))
        else:
            xticks_labels.append(current_date.strftime(f"%d{iwn}"))
    elif current_date.month != tmp2:
        xticks_positions.append(tmp)
        xticks_labels.append(current_date.strftime(f"%m月{iwn}"))
    elif tmp % 24 == 0:
        xticks_positions.append(tmp)
        xticks_labels.append(current_date.strftime(f"%d{iwn}"))
    tmp2 = current_date.month
    current_date += timedelta(hours=4)
plt.xticks(xticks_positions, xticks_labels, fontweight="bold", c="white")

plt.yticks([])  # y轴坐标不显示

plt.grid(
    True,
    which="major",
    linestyle="--",
    color=[0.2, 0.2, 0.2],
    linewidth=1,
)  # 设置主刻度线的网格线
plt.grid(
    True,
    which="minor",
    linestyle=":",
    color="gray",
    linewidth=0.75,
)  # 设置副刻度线的网格线

plt.fill_betweenx(
    [-0.5, df.shape[0] - 0.5],
    24 * 左边界距今天,
    24 * 左边界距今天 + 24,
    color="white",
    alpha=0.3,
)

plt.xlim(0, rb)  # 设置x轴的范围为left_border和right_border之间
plt.ylim(-0.5, df.shape[0] - 0.5)  # 调整y轴上下空隙

ax.spines[["right", "left"]].set_visible(False)  # 去掉左右y轴边框

plt.tight_layout()  # 这样布局会好看一点

plt.savefig(f"./粥历.png")
