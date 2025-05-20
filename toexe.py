import os

os.system(
    r"pyinstaller -F -w F:\myPython\GanttKnights\main.py -n zl --add-data '背景图;背景图' --add-data '纹理;纹理' --add-data '所有活动数据.csv;.' --add-data '活动数据.csv;.' --add-data 'debug_page.html;.' --add-data 'zl.ico;.'"
)

os.system(r'copy .\dist\zl.exe .\zl.exe')
