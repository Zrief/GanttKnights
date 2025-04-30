import matplotlib.pyplot as plt
import matplotlib.image as image
from matplotlib.ticker import MultipleLocator
import pandas as pd
from datetime import datetime, timedelta
from dateutil.parser import parse
import numpy as np
from PIL import Image as PILimage
from glob import glob
from random import choice


def get_random_paths() -> tuple[str, str, str, str]:
    """
    获取随机的背景图片路径、纹理路径以及活动数据文件路径。

    返回:
    tuple[str, str, str, str]: 背景图片路径、纹理路径、所有活动数据文件路径、活动数据文件路径。
    """
    background_list = glob(f"./粥图" + "/*")
    background_pic_dir = choice(background_list)
    texture_list = glob(f"./纹理" + "/*")
    texture_dir = choice(texture_list)
    all_data_path = r"./所有活动数据.csv"
    data_path = r"./活动数据.csv"
    return background_pic_dir, texture_dir, all_data_path, data_path


def preprocess_data(
    data_path: str,
    all_data_path: str,
    now: datetime,
    left_border: datetime,
    right_border: datetime,
) -> pd.DataFrame:
    """
    对活动数据进行预处理，包括日期标准化、删除过期和未到事件、排序并保存处理后的数据。

    参数:
    data_path (str): 活动数据文件路径。
    all_data_path (str): 所有活动数据文件路径。
    now (datetime): 当前时间。
    left_border (datetime): 绘图的左边界时间。
    right_border (datetime): 绘图的右边界时间。

    返回:
    pd.DataFrame: 处理后的活动数据 DataFrame。
    """
    df = pd.read_csv(all_data_path)
    df.iloc[:, 1] = [parse(ii) for ii in df.iloc[:, 1]]
    df.iloc[:, 2] = [parse(ii) for ii in df.iloc[:, 2]]
    df = df.loc[df.iloc[:, 2] > now + timedelta(hours=4)]
    df = df.loc[df.iloc[:, 1] < right_border]
    df = df.sort_values(by=["类型", "结束时间","开始时间"], ascending=False)
    df.to_csv(data_path, index=False)
    return df


def extract_main_colors(background_pic_dir: str, num_colors: int) -> list[str]:
    """
    从背景图片中提取主要颜色。

    参数:
    background_pic_dir (str): 背景图片的路径。
    num_colors (int): 要提取的主要颜色数量。

    返回:
    list[str]: 提取的主要颜色的十六进制表示列表。
    """
    color = []
    pilimg = PILimage.open(background_pic_dir)
    small_image = pilimg.resize((80, 80))
    result = small_image.convert("P", palette=PILimage.ADAPTIVE, colors=num_colors)
    result = result.convert("RGB")
    main_colors = result.getcolors()
    col_extract = []
    for count, col in main_colors:
        col_extract.append([col[i] / 255 for i in range(3)])
        if sum(col) > 255 * 3 * 0.382:
            r, g, b = col
            r, g, b = (
                round(np.sqrt(r / 255) * 255),
                round(np.sqrt(g / 255) * 255),
                round(np.sqrt(b / 255) * 255),
            )
            result = (r << 16) + (g << 8) + b
            color.append("#" + hex(result)[2:])
    return color


def set_alpha_channel(image_data: np.ndarray, alphavalue: float) -> np.ndarray:
    """
    为图像添加或修改 Alpha 通道。

    参数:
    image_data (np.ndarray): 图像数据的 NumPy 数组。
    alphavalue (float): Alpha 通道的值，可以是 0 到 1 之间的小数，也可以是 0 到 255 之间的整数。

    返回:
    np.ndarray: 带有 Alpha 通道的图像数据的 NumPy 数组。
    """
    alpha_val = np.clip(round(alphavalue * 255) if alphavalue <= 1.0 else round(alphavalue), 0, 255).astype(np.uint8)
    if image_data.shape[2] not in (3, 4):
        raise ValueError("Input image must have 3 (RGB) or 4 (RGBA) channels.")
    if image_data.shape[2] == 3:
        alpha = np.full(
            (image_data.shape[0], image_data.shape[1]), alpha_val, dtype=np.uint8
        )
        return np.dstack((image_data, alpha))
    else:
        image_data = image_data.copy()
        image_data[:, :, 3] = alpha_val
        return image_data


def plot_events(
    df: pd.DataFrame, left_border: datetime, right_border: datetime, color: list[str]
) -> None:
    """
    绘制活动事件的条形图，并添加事件名称。

    参数:
    df (pd.DataFrame): 包含活动数据的 DataFrame，第一列是事件名称，第二列是开始时间，第三列是结束时间。
    left_border (datetime): 绘图的左边界时间。
    right_border (datetime): 绘图的右边界时间。
    color (list[str]): 用于绘制条形图的颜色列表。

    返回:
    int: 绘制的事件总数。
    """
    total_event_num = 0
    rb = (right_border - left_border).total_seconds() // 3600
    for ii, name in enumerate(df.iloc[:, 0]):
        start_time = df.iloc[ii, 1]
        end_time = df.iloc[ii, 2]
        tmp1 = (end_time - start_time).total_seconds() // 3600
        tmp2 = (end_time - left_border).total_seconds() // 3600
        width = min(tmp1, tmp2) + 1
        left = max((start_time - left_border).total_seconds() // 3600, -1)
        if tmp2 > 0 and left < rb and left + width >= 3 * 24:
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
            tmp3 = (right_border - start_time).total_seconds() // 3600
            lwth = min(width, tmp3, rb)
            namestr = name[: lwth // 8] if lwth <= 24 * 3 else name
            plt.text(
                x=left + lwth / 2,
                y=ii,
                s=namestr,
                va="center",
                ha="center",
                fontweight="bold",
            )
            total_event_num += 1


def set_x_ticks(ax: plt.Axes, left_border: datetime, right_border: datetime) -> None:
    """
    设置 x 轴的刻度和标签。

    参数:
    ax (plt.Axes): 绘图的 Axes 对象。
    left_border (datetime): 绘图的左边界时间。
    right_border (datetime): 绘图的右边界时间。

    返回:
    None
    """
    ax.minorticks_on()
    ax.tick_params(axis="both", which="major", direction="in", width=1, length=5)
    ax.tick_params(axis="both", which="minor", direction="in", width=1, length=2)
    ax.xaxis.set_minor_locator(MultipleLocator(4))
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
            if (
                current_date.day + 3 + 22 - current_date.weekday()
                < (
                    current_date.replace(month=(current_date.month + 1) % 12, day=1)
                    - timedelta(days=1)
                ).day
            ):
                xticks_labels.append(current_date.strftime(f"%m月{iwn}"))
            else:
                xticks_labels.append(current_date.strftime(f"%d{iwn}"))
            xticks_positions.append(tmp)
        elif current_date.month != tmp2:
            xticks_labels.append(current_date.strftime(f"%m月{iwn}"))
            xticks_positions.append(tmp)
        elif tmp % 24 == 0:
            xticks_labels.append(current_date.strftime(f"%d{iwn}"))
            xticks_positions.append(tmp)
        tmp2 = current_date.month
        current_date += timedelta(hours=4)
    plt.xticks(xticks_positions, xticks_labels, fontweight="bold", c="white")


def main() -> None:
    num_colors = 10
    background_pic_dir, texture_dir, all_data_path, data_path = get_random_paths()
    now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_weekday = now.weekday()
    left_border = now - timedelta(days=3)
    right_border = now + timedelta(days=22 - today_weekday)
    df = preprocess_data(data_path, all_data_path, now, left_border, right_border)
    color = extract_main_colors(background_pic_dir, num_colors)
    plt.rcParams["font.sans-serif"] = ["SimHei"]
    plt.rcParams["font.size"] = 16
    fig = plt.figure(figsize=(16, 9), facecolor="silver")
    ax = plt.subplot(111, frameon=False)
    img = image.imread(background_pic_dir)
    tw = image.imread(texture_dir)
    img = set_alpha_channel(img, 0.6)
    tw = set_alpha_channel(tw, 0.2)
    img[:, :, :-1] = img[:, :, :-1] / 3
    fig.figimage(img, 0, 0, zorder=-3)
    fig.figimage(tw, 0, 0, zorder=-2)
    plot_events(df, left_border, right_border, color)
    plt.title("近期活动一览", c="white")
    set_x_ticks(ax, left_border, right_border)
    plt.yticks([])
    plt.grid(
        True,
        which="major",
        linestyle="--",
        color=[0.2, 0.2, 0.2],
        linewidth=1,
    )
    plt.grid(
        True,
        which="minor",
        linestyle=":",
        color="gray",
        linewidth=0.75,
    )
    plt.fill_betweenx(
        [-0.5, df.shape[0] - 0.5],
        24 * 3,
        24 * 3 + 24,
        color="white",
        alpha=0.3,
    )
    plt.xlim(0, (right_border - left_border).total_seconds() // 3600)
    plt.ylim(-0.5, df.shape[0] - 0.5)
    ax.spines[["right", "left"]].set_visible(False)
    plt.tight_layout()
    plt.savefig(f"./粥历.png")


if __name__ == "__main__":
    main()
