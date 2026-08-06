"""
2023国赛C题 · 问题一：蔬菜销量分布规律与相互关系分析
==================================================
这是你的起点文件。思路参考 reference_solution/ 里的代码，
但请先自己试着写，遇到问题再去看参考。

运行方式：
    python notebooks/01_question1_eda.py
或在 Jupyter 中打开对应的 .ipynb
"""
import os
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # 非交互后端，只保存图片不弹窗
import matplotlib.pyplot as plt
from scipy import stats

# ============================================================
# 0. 路径设置
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
OUTPUT_DIR = os.path.join(ROOT_DIR, 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 中文显示
matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False

# ============================================================
# 1. 数据加载
# ============================================================
# TODO: 下载原始附件到 data/ 后，取消下面的注释
# df1 = pd.read_excel(os.path.join(ROOT_DIR, 'data', '附件1.xlsx'))
# df2 = pd.read_excel(os.path.join(ROOT_DIR, 'data', '附件2.xlsx'))
# df3 = pd.read_excel(os.path.join(ROOT_DIR, 'data', '附件3.xlsx'))
# df4 = pd.read_excel(os.path.join(ROOT_DIR, 'data', '附件4.xlsx'))

# 临时方案：使用参考解法的处理数据熟悉结构
REF_FILE = os.path.join(ROOT_DIR, 'reference_solution', '数据', '品类数据总表（不含公式）.xlsx')
print(f"读取处理数据: {REF_FILE}")
df_category = pd.read_excel(REF_FILE)
print("=== 品类数据总表 ===")
print(df_category.info())
print(df_category.head())
print(df_category.describe())

# ============================================================
# 2. 数据预处理（等你有了原始数据后做）
# ============================================================
"""
预处理清单：
□ 缺失值：检查 df2 中销量、单价是否有空值 → 插值或填0
□ 异常值：用 3σ 准则或箱线图检测 → 剔除或修正
□ 日期格式：统一为 datetime 类型
□ 数据合并：将附件1~4关联（用单品编码做 key）
"""

# ============================================================
# 3. 问题1-1：销量分布规律
# ============================================================
print("\n" + "="*60)
print("问题1-1：蔬菜各品类及单品销售量的分布规律")
print("="*60)

# 3.1 按品类汇总的销量分布
category_sales = df_category.groupby('分类名称')['当日销量'].agg(['sum','mean','std','count'])
print("\n品类销量统计：")
print(category_sales)

# 绘制品类销量柱状图
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# 总销量
category_sales['sum'].sort_values().plot(
    kind='barh', ax=axes[0], color='steelblue'
)
axes[0].set_title('各品类总销量（3年）')
axes[0].set_xlabel('总销量(kg)')

# 日均销量箱线图
df_category.boxplot(column='当日销量', by='分类名称', ax=axes[1], rot=45)
axes[1].set_title('各品类单日销量分布')
axes[1].set_ylabel('销量(kg)')

plt.suptitle('')
plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, 'q1_category_distribution.png'), dpi=150)
plt.close()

# 3.2 季节性分析（按月）
df_category['月份'] = pd.to_datetime(df_category['销售日期']).dt.month
monthly = df_category.groupby(['分类名称', '月份'])['当日销量'].mean().unstack()

fig, ax = plt.subplots(figsize=(12, 6))
monthly.T.plot(ax=ax, marker='o')
ax.set_title('各品类月均销量趋势')
ax.set_xlabel('月份')
ax.set_ylabel('月均销量(kg)')
ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, 'q1_seasonal_trend.png'), dpi=150)
plt.close()

# ============================================================
# 4. 问题1-2：品类/单品间的相互关系
# ============================================================
print("\n" + "="*60)
print("问题1-2：蔬菜品类的相互关系（Pearson相关系数）")
print("="*60)

# 构建品类日销量矩阵（透视表）
pivot = df_category.pivot_table(
    values='当日销量', index='销售日期', columns='分类名称', aggfunc='sum'
).fillna(0)

# Pearson 相关系数
corr_matrix = pivot.corr(method='pearson')
print(corr_matrix)

# 热力图
import seaborn as sns
fig, ax = plt.subplots(figsize=(8, 6))
sns.heatmap(corr_matrix, annot=True, cmap='RdBu_r', center=0,
            vmin=-1, vmax=1, square=True, ax=ax,
            fmt='.2f', linewidths=0.5)
ax.set_title('蔬菜品类销量 Pearson 相关系数热力图')
plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, 'q1_corr_heatmap.png'), dpi=150)
plt.close()

# 找出相关性最强的品类对
print("\n相关性最强的品类对（|r| > 0.5）：")
found = False
for i in range(len(corr_matrix.columns)):
    for j in range(i+1, len(corr_matrix.columns)):
        r = corr_matrix.iloc[i, j]
        if abs(r) > 0.5:
            print(f"  {corr_matrix.columns[i]} <-> {corr_matrix.columns[j]}: r = {r:.3f}")
            found = True
if not found:
    print("  没有 |r| > 0.5 的品类对")

print(f"\n[OK] 问题1分析完成！输出图片保存在 {OUTPUT_DIR}")
