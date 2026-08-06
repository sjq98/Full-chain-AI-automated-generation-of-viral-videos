# -*- coding: utf-8 -*-
"""技术路线图:四问串一张图,输出到 paper/技术路线图.png"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import matplotlib.font_manager as fm

# 中文字体
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

fig, ax = plt.subplots(figsize=(11, 8.5))
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)
ax.axis('off')

C_BLUE = '#2F5597'
C_LIGHT = '#DCE6F1'
C_GREEN = '#548235'
C_ORANGE = '#C55A11'
C_GRAY = '#595959'

def box(x, y, w, h, text, fc=C_LIGHT, ec=C_BLUE, fs=11, tc='black'):
    b = FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.4',
                       fc=fc, ec=ec, lw=1.6)
    ax.add_patch(b)
    ax.text(x + w/2, y + h/2, text, ha='center', va='center',
            fontsize=fs, color=tc, linespacing=1.5)

def arrow(x1, y1, x2, y2, color=C_BLUE):
    a = FancyArrowPatch((x1, y1), (x2, y2), arrowstyle='-|>',
                        mutation_scale=18, lw=1.8, color=color)
    ax.add_patch(a)

# 第1层:数据
box(30, 90, 40, 8, '数据层:附件1~4\n(251单品 · 878,503条流水 · 55,983条批发价 · 损耗率)', fc='#FFF2CC', ec=C_ORANGE, fs=11)

# 第2层:预处理
box(30, 76, 40, 8, '数据预处理:清洗 · 异常值剔除 · 按品类/单品聚合', fc=C_LIGHT, ec=C_BLUE)
arrow(50, 90, 50, 84.6)

# 第3层:四个问题
box(4, 50, 20, 16, '问题一\n分布规律\n与相互关系\n\n描述统计\n相关分析\n聚类', fc=C_LIGHT, ec=C_BLUE, fs=10.5)
box(28, 50, 20, 16, '问题二\n品类级\n补货与定价\n\n回归分析\nARIMA预测\n收益优化', fc=C_LIGHT, ec=C_BLUE, fs=10.5)
box(52, 50, 20, 16, '问题三\n单品级\n补货与定价\n\n单品筛选\n混合整数\n规划', fc=C_LIGHT, ec=C_BLUE, fs=10.5)
box(76, 50, 20, 16, '问题四\n数据需求\n建议\n\n需求侧/供给侧\n环境侧数据', fc=C_LIGHT, ec=C_BLUE, fs=10.5)

for cx in (14, 38, 62, 86):
    arrow(cx, 76, cx, 66.8)

# 支撑信息
box(4, 26, 92, 10, '模型支撑:时间序列预测(ARIMA) · 收益最大化优化 · 0-1混合整数规划 · 灵敏度分析', fc='#E2EFDA', ec=C_GREEN, fs=10.5)
arrow(28, 50, 28, 36.6)
arrow(62, 50, 62, 36.6)

# 输出层
box(20, 8, 60, 10, '输出:未来一周各品类日补货总量与定价策略\n7月1日单品补货清单(27-33个)与定价 · 数据采集建议', fc='#FCE4D6', ec=C_ORANGE, fs=11)
arrow(14, 50, 14, 18.8)
arrow(86, 50, 86, 18.8)
arrow(50, 26, 50, 18.8)

plt.tight_layout()
plt.savefig('paper/技术路线图.png', dpi=150, bbox_inches='tight', facecolor='white')
print('已输出 paper/技术路线图.png')
