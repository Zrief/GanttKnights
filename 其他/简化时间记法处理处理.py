import pandas as pd
from datetime import datetime, timedelta
from dateutil.parser import (
    parse,
)  # 识别日期字符串。使得时间可以简写成 2024-11-1 16h 而非2024-11-1 16:00:00

"""简化时间记法处理处理 """
all_data_path = r"./所有活动数据.csv"

# 数据读取与数据整理
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

df.to_csv(all_data_path,index=False)