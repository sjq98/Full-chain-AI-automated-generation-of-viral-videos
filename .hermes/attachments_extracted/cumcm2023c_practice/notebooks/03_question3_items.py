"""
2023国赛C题 · 问题三：单品级补货与定价优化
============================================
Day2晚上-Day3上午使用。
约束：可售单品总数 27-33 个，最小陈列量 2.5kg
输出：7月1日的单品补货量 + 定价策略

运行：
    python notebooks/03_question3_items.py
"""
import os, sys
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
OUTPUT_DIR = os.path.join(ROOT_DIR, 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False

print("="*60)
print("问题三：单品级补货与定价策略")
print("="*60)

# ============================================================
# 1. 数据加载
# ============================================================
# TODO: 有原始附件后，用附件1~4
# 这里用参考解法的单品数据
SINGLE_FILE = os.path.join(ROOT_DIR, 'reference_solution', '数据', '单品数据总表.xlsx')
if os.path.exists(SINGLE_FILE):
    df_single = pd.read_excel(SINGLE_FILE)
    print(f"读取单品数据: {SINGLE_FILE}")
    print(f"列: {df_single.columns.tolist()}")
    print(f"单品数: {df_single['单品名称'].nunique() if '单品名称' in df_single.columns else 'N/A'}")
    print(df_single.head())
else:
    print("⚠️ 单品数据总表未找到，请先下载原始附件")
    # 用品类数据模拟
    print("→ 使用品类数据做演示...")

# ============================================================
# 2. 可售单品筛选
# ============================================================
print("\n" + "-"*40)
print("Step 1: 筛选 27-33 个可售单品")
print("-"*40)

# 筛选逻辑（你需要根据实际数据调整）：
# 1. 从附件3取6月24-30日有批发价记录的单品（可进货）
# 2. 从附件2取这7天有销量的单品（有需求）
# 3. 按收益/需求量排序，取 top 27-33
# 4. 确保每个品类至少有2-3个单品

print("""
筛选策略建议：
  1. 计算每个单品的「利润贡献度」= 日均利润 * 需求稳定度
  2. 按品类分层抽样，每品类至少保留2个单品
  3. 优先保留高利润、高需求、低损耗的单品
  4. 注意品类间的搭配关系（问题1的相关性结论）
  
  伪代码：
    candidates = 可进货 & 有历史销量
    candidates['score'] = profit_rank * 0.6 + stability_rank * 0.4
    selected = top_k_per_category(candidates, k_min=2, total=30)
""")

# ============================================================
# 3. 需求预测（单品粒度）
# ============================================================
print("\n" + "-"*40)
print("Step 2: 预测7月1日各单品需求")
print("-"*40)

print("""
预测方法（按优先级）：
  1. 如果单品历史销量充足 → LSTM / Prophet
  2. 如果数据中等 → ARIMA / 指数平滑
  3. 如果数据稀疏 → 用同品类均值 + 该单品占比
  4. 考虑星期效应（7月1日是周六）
""")

# ============================================================
# 4. 优化模型
# ============================================================
print("\n" + "-"*40)
print("Step 3: 多目标优化模型")
print("-"*40)

print("""
决策变量：x_i = 单品i的补货量(kg), p_i = 单品i的定价(元/kg)
目标函数：
  max 总利润 = Σ[ p_i * min(x_i, d_i) - c_i * x_i - loss_i ]
  min 供需缺口 = Σ| x_i - d_i | / d_i
  
约束条件：
  (1) 27 ≤ 单品数 ≤ 33
  (2) x_i ≥ 2.5 (最小陈列量)
  (3) Σ x_i ≤ 销售空间上限
  (4) p_i ∈ [成本价*0.8, 市场价*1.2]
  (5) 每种单品必须满足该品类市场需求的某个比例

求解方法：
  - 精确解：混合整数非线性规划 (MINLP) → BONMIN求解器
  - 启发式：遗传算法 / 模拟退火 / 粒子群
  - 参考: reference_solution/代码/第三问求解混合规划.py
""")

# ============================================================
# 5. 输出结果
# ============================================================
print("\n" + "-"*40)
print("Step 4: 生成结果表")
print("-"*40)

print("""
结果表格式（每个选中单品一行）：

| 单品名称 | 品类 | 预测需求(kg) | 补货量(kg) | 定价(元/kg) | 预计利润(元) |
|---------|------|-------------|-----------|------------|------------|

输出文件：output/q3_item_plan.csv
""")

print(f"\n[OK] 问题3框架已加载。等你拿到原始数据后填入具体数值即可运行。")
