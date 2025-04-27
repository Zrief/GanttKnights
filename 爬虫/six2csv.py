import pandas as pd
from dateutil.parser import parse


def transform_data(input_str: str):
    """
    将日期字符串转换为标准日期格式
    """
    try:
        input_str = input_str.replace("日", " ").replace("月", "-")
        input_str = input_str.replace("年", "-")
        return parse(input_str)
    except ValueError:
        return pd.NaT


def read_data(file_path):
    """
    读取CSV文件并返回DataFrame
    """
    try:
        return pd.read_csv(file_path)
    except FileNotFoundError:
        print(f"错误：未找到 {file_path} 文件，请检查文件路径和文件名是否正确。")
        return None
    except Exception as e:
        print(f"读取文件 {file_path} 时出现未知错误：{e}")
        return None


def filter_non_null_stars(df):
    """
    过滤掉六星干员列为空的数据
    """
    return df[~df["六星干员"].isnull()]
    


def process_date_columns(df):
    """
    处理日期列，将日期字符串转换为标准日期格式
    """
    df.iloc[:, 1] = [transform_data(ii) for ii in df.iloc[:, 1]]
    df.iloc[:, 2] = [transform_data(ii) for ii in df.iloc[:, 2]]
    return df


def process_name_column(df):
    """
    处理名称列，进行字符串替换和拼接
    重命名活动类型列为名称列
    添加类型列并删除六星干员列
    """
    df.iloc[:, 0] = (
        df.iloc[:, 0]
        .str.replace("常驻标准寻访", "【标准池】")
        .str.replace("中坚寻访", "【中坚池】")
    )
    mask = df.iloc[:, 0].str.contains('限定寻访·庆典')
    df.loc[mask, df.columns[0]] = '【限定池】'

    df.iloc[:, 0] = df.iloc[:, 0] + df.iloc[:, 3].str.replace("[限定]","")

    df.rename(columns={"活动类型": "名称"}, inplace=True)
    
    df["类型"] = 0
    df = df.drop("六星干员", axis=1)
    return df

def merge_dataframes(df1, df2):
    """
    合并两个DataFrame
    数据后处理，包括数据类型转换、去重和排序
    """
    df = pd.concat([df1, df2], axis=0, ignore_index=True)
    df = df.convert_dtypes()
    df = df.drop_duplicates(df.columns[0])
    df['开始时间'] = pd.to_datetime(df['开始时间'], errors='coerce')
    df = df.sort_values(by="开始时间", ascending=True)
    return df

def save_data(df, file_path):
    """
    将DataFrame保存为CSV文件
    """
    try:
        df.to_csv(file_path, index=False)
    except Exception as e:
        print(f"保存文件 {file_path} 时出现错误：{e}")


def process_data(skdpath: str = "arknights_events.csv", oppath: str = "爬虫/卡池.csv"):
    """
    主处理函数，调用其他函数完成数据处理流程
    """
    
    df = read_data(skdpath)
    if df is None:
        return

    df = filter_non_null_stars(df)
    df = process_date_columns(df)
    df = process_name_column(df)

    df2 = read_data(oppath)
    if df2 is None:
        return

    df = merge_dataframes(df2, df)

    save_data(df, oppath)
    
    final_path = ".\所有活动数据.csv"
    save_data(merge_dataframes(read_data(final_path),df),final_path)
    return df


if __name__ == "__main__":
    process_data()
    