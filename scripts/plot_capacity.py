"""Plot measured point summaries; no interpolation or synthetic capacity points."""
import argparse
import csv
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

parser = argparse.ArgumentParser()
parser.add_argument('output', type=Path)
parser.add_argument('summaries', nargs='+', type=Path)
args = parser.parse_args()
points = [json.loads(path.read_text()) for path in args.summaries]
points.sort(key=lambda point: point['p_kv_budget_bytes_per_card'])
args.output.mkdir(parents=True, exist_ok=True)
with (args.output / 'summary.csv').open('w', newline='') as handle:
    writer = csv.DictWriter(handle, fieldnames=list(points[0]))
    writer.writeheader()
    writer.writerows(points)
valid = [point for point in points if point['success'] == point['planned'] == 174
         and point['failed'] == point['not_recorded'] == 0]
assert len(valid) >= 2, 'Two complete capacity points required for comparison charts'
x = [point['p_kv_budget_bytes_per_card'] / 2**30 for point in valid]
plt.rcParams.update({'font.size': 11, 'axes.spines.top': False, 'axes.spines.right': False})
fig, ax = plt.subplots(figsize=(7, 4.5), constrained_layout=True)
y = [point['p_local_hit_fraction'] * 100 for point in valid]
ax.scatter(x, y, s=65, color='#2276b5')
for point, xx, yy in zip(valid, x, y):
    ax.annotate(f"{point['label']}: {yy:.2f}%", (xx, yy), xytext=(0, 10),
                textcoords='offset points', ha='center')
ax.set(xlabel='P KV memory budget per GPU (GiB; runtime confirmed)',
       ylabel='P local prefix hit rate (%)', ylim=(0, 105), xticks=x,
       title='Fixed trace: local prefix reuse vs P capacity')
ax.grid(axis='y', alpha=.2)
fig.savefig(args.output / 'capacity-hit-rate.png', dpi=180)
plt.close(fig)
fig, ax = plt.subplots(figsize=(7, 4.5), constrained_layout=True)
for statistic, marker, color in [('p50', 'o', '#2276b5'), ('p95', '^', '#d97924')]:
    y = [point[f'continuation_ttft_{statistic}_seconds'] for point in valid]
    ax.scatter(x, y, marker=marker, s=65, label=statistic.upper(), color=color)
ax.set(xlabel='P KV memory budget per GPU (GiB; runtime confirmed)',
       ylabel='Continuation TTFT (seconds)', xticks=x,
       title='Fixed trace: continuation TTFT vs P capacity')
ax.set_ylim(bottom=0)
ax.legend()
ax.grid(axis='y', alpha=.2)
fig.savefig(args.output / 'capacity-ttft.png', dpi=180)
plt.close(fig)
